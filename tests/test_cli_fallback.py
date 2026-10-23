"""CLI uses real SQLite state, but never sends a real Codex chat message."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from coordinator.board import Board
from coordinator.cli import main
from coordinator.handoff import Handoffs
from coordinator.store import Store


PLUGIN = Path(__file__).resolve().parents[1]/'plugins/resource-coordinator'
RESOURCE = [{"key":"cli-test:output", "mode":"exclusive"}]


@pytest.fixture
def cli(tmp_path, capsys):
    database = tmp_path/'state.sqlite3'

    def invoke(*args, ok=True):
        code = main(['--db',str(database),*map(str,args)])
        out = capsys.readouterr()
        assert code == (0 if ok else 1), (code,out)
        assert not (out.err if ok else out.out)
        text = out.out if ok else out.err
        assert 'Traceback' not in text
        return json.loads(text)

    return database,invoke


def pending_notice(database):
    store = Store(database)
    board, handoffs = Board(store), Handoffs(store)
    for actor in ('a','b','c'):
        board.register(actor,actor,'test')
        handoffs.configure(actor,True,'synthetic test scope')
    first = store.request('a','first',RESOURCE)
    lease = store.acquire(first['id'],'a')
    target = store.request('b','second',RESOURCE)
    store.finish(first['id'],'a',lease['lease_token'])
    notice = handoffs.listing('a')['notices'][0]
    return store,handoffs,target,notice


def test_registration_report_bom_revision_and_changes(cli, tmp_path):
    database,call = cli
    registered = call('register-chat','--chat','a','--label','测试甲','--project-key','测试项目')
    assert registered['work_revision'] == 0
    payload = dict(chat_id='a',reporter='a',work_state='working',summary='正在修复',expected_revision=0,
                   provenance={'base_commit':'abc','dirty':True,'write_scope':['coordinator/cli.py'],'evidence':[]})
    path = tmp_path/'report.json'
    path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8-sig')
    result = call('report-status','--input',path)
    assert result['work_revision'] == 1
    view = call('board','--project-key','测试项目')
    assert view['chats'][0]['summary'] == '正在修复'
    assert view['chats'][0]['adoption'] == 'self_reported'
    assert view['queue'] == []
    call('report-status','--input',path,ok=False)  # stale revision never overwrites
    changes = call('changes','--observer','a')
    assert changes['changes']
    call('ack-changes','--observer','a','--cursor',changes['next_cursor'])
    assert call('changes','--observer','a')['changes'] == []
    assert Board(Store(database)).view()['chats'][0]['work_revision'] == 1


@pytest.mark.parametrize('change', [
    {'reporter':'somebody-else'}, {'expected_revision':True}, {'expected_revision':-1},
    {'extra':'not-allowed'}, {'work_state':[]}, {'provenance':[]},
])
def test_malformed_or_peer_reports_do_not_change_state(cli, tmp_path, change):
    database,call = cli
    call('register-chat','--chat','a','--label','A','--project-key','test')
    payload = dict(chat_id='a',reporter='a',work_state='working',summary='test',expected_revision=0)
    payload.update(change)
    path = tmp_path/'bad.json'
    path.write_text(json.dumps(payload),encoding='utf-8')
    call('report-status','--input',path,ok=False)
    assert Board(Store(database)).view()['chats'][0]['work_revision'] == 0


@pytest.mark.parametrize('text', ['[]','{bad','{"expected_revision": NaN}'])
def test_bad_json_is_a_structured_error(cli, tmp_path, text):
    _,call = cli
    path = tmp_path/'bad.json'
    path.write_text(text,encoding='utf-8')
    result = call('report-status','--input',path,ok=False)
    assert result['command_started'] is False


def test_set_dependencies_keeps_original_waiting_and_cycle_rules(cli):
    _,call = cli
    def request(owner):
        return call('request','--owner',owner,'--purpose','test','--resources',json.dumps(RESOURCE))
    first,second = request('a'),request('b')
    result = call('set-dependencies','--request',second['id'],'--owner','b','--depends-on',json.dumps([first['id']]))
    assert result['dependency_blockers'][0]['id'] == first['id']
    call('set-dependencies','--request',first['id'],'--owner','a','--depends-on',json.dumps([second['id']]),ok=False)


def test_enable_needs_scope_and_does_not_send(cli):
    _,call = cli
    call('register-chat','--chat','a','--label','A','--project-key','test')
    call('notifications','configure','--chat','a','--enable',ok=False)
    result = call('notifications','configure','--chat','a','--enable','--authorization-reference','synthetic scope')
    assert result['enabled'] is True
    assert call('notifications','list','--actor','a')['notices'] == []
    call('notifications','configure','--chat','a','--disable')
    assert call('notifications','list','--actor','a')['enabled'] is False


def test_claim_file_redaction_and_actual_result_ack_are_separate(cli, tmp_path):
    database,call = cli
    store,handoffs,target,notice = pending_notice(database)
    path = tmp_path/'delivery.claim.json'
    result = call('notifications','claim','--notice',notice['id'],'--actor','a','--claim-file',path)
    token = json.loads(path.read_text(encoding='utf-8'))['claim']['claim_token']
    assert result['message_sent'] is False and result['token_redacted']
    assert token not in json.dumps(result)
    assert token not in json.dumps(call('board'))
    assert token not in json.dumps(call('notifications','list','--actor','a'))
    assert result['host_arguments']['threadId'] == 'b'
    call('notifications','ack','--claim-file',path,'--outcome','delivered','--receipt-thread-id','wrong',ok=False)
    assert handoffs.listing('a')['notices'][0]['state'] == 'sending'
    # Synthetic host receipt only; this is NOT a real cross-chat delivery test.
    result = call('notifications','ack','--claim-file',path,'--outcome','delivered','--receipt-thread-id','b')
    assert result['delivery_accepted'] and not result['recipient_read_verified']
    assert not result['reservation_acquired']
    assert store.status(target['id'])['state'] == 'waiting'
    assert handoffs.listing('a')['notices'] == []
    call('notifications','ack','--claim-file',path,'--outcome','delivered','--receipt-thread-id','b',ok=False)


def test_claim_refuses_existing_file_before_mutating_notice(cli, tmp_path):
    database,call = cli
    _,handoffs,_,notice = pending_notice(database)
    path = tmp_path/'existing.claim.json'
    path.write_text('do not overwrite',encoding='utf-8')
    call('notifications','claim','--notice',notice['id'],'--actor','a','--claim-file',path,ok=False)
    assert path.read_text(encoding='utf-8') == 'do not overwrite'
    assert handoffs.listing('a')['notices'][0]['state'] == 'pending'


def test_claim_persistence_failure_never_claims_delivery(cli, tmp_path, monkeypatch):
    database,call = cli
    _,handoffs,_,notice = pending_notice(database)
    def fail(_fd):
        raise OSError('synthetic disk error')
    monkeypatch.setattr('coordinator.cli.os.fsync',fail)
    result = call('notifications','claim','--notice',notice['id'],'--actor','a','--claim-file',tmp_path/'failed.claim.json',ok=False)
    assert 'Do not claim again' in result['error']
    assert handoffs.listing('a')['notices'][0]['state'] == 'sending'


def test_receipt_for_different_database_is_rejected(cli, tmp_path):
    database,call = cli
    _,handoffs,_,notice = pending_notice(database)
    path = tmp_path/'wrong-db.claim.json'
    call('notifications','claim','--notice',notice['id'],'--actor','a','--claim-file',path)
    receipt = json.loads(path.read_text(encoding='utf-8'))
    receipt['database'] = str(tmp_path/'other.sqlite3')
    path.write_text(json.dumps(receipt),encoding='utf-8')
    call('notifications','ack','--claim-file',path,'--outcome','delivered','--receipt-thread-id','b',ok=False)
    assert handoffs.listing('a')['notices'][0]['state'] == 'sending'


def test_definite_failure_can_retry_but_uncertainty_cannot(cli, tmp_path):
    database,call = cli
    _,handoffs,_,notice = pending_notice(database)
    path = tmp_path/'first.claim.json'
    call('notifications','claim','--notice',notice['id'],'--actor','a','--claim-file',path)
    call('notifications','ack','--claim-file',path,'--outcome','not_sent','--result-code','tool_unavailable')
    call('notifications','archive','--notice',notice['id'],'--actor','a',ok=False)
    call('notifications','retry','--notice',notice['id'],'--actor','c',ok=False)
    call('notifications','retry','--notice',notice['id'],'--actor','c','--confirmed-not-sent')
    second = tmp_path/'second.claim.json'
    call('notifications','claim','--notice',notice['id'],'--actor','c','--claim-file',second)
    call('notifications','ack','--claim-file',path,'--outcome','delivered','--receipt-thread-id','b',ok=False)
    call('notifications','ack','--claim-file',second,'--outcome','uncertain','--result-code','transport_uncertain')
    call('notifications','retry','--notice',notice['id'],'--actor','c','--confirmed-not-sent',ok=False)
    call('notifications','archive','--notice',notice['id'],'--actor','c',ok=False)
    assert handoffs.listing('a')['notices'][0]['state'] == 'uncertain'


def test_obsolete_pending_notice_can_archive_but_waiter_cannot(cli):
    database,call = cli
    store,handoffs,target,notice = pending_notice(database)
    call('notifications','archive','--notice',notice['id'],'--actor','a',ok=False)
    prerequisite = store.request('c','new prerequisite',[{'key':'cli-test:other','mode':'exclusive'}])
    store.set_dependencies(target['id'],'b',[prerequisite['id']])
    assert not handoffs.listing('a')['notices'][0]['eligible_now']
    call('notifications','archive','--notice',notice['id'],'--actor','a',ok=False)
    store.cancel(target['id'],'b')
    call('notifications','archive','--notice',notice['id'],'--actor','b',ok=False)
    result = call('notifications','archive','--notice',notice['id'],'--actor','a')
    assert result['state'] == 'obsolete' and result['message_sent'] is False
    assert call('notifications','archive','--notice',notice['id'],'--actor','a')['already_archived']
    assert handoffs.listing('a')['notices'] == []
    assert handoffs.listing('a',True)['notices'][0]['state'] == 'obsolete'
    assert store.status(target['id'])['state'] == 'cancelled'


def test_no_longer_waiting_claim_is_deferred_not_sent(cli, tmp_path):
    database,call = cli
    store,_,target,notice = pending_notice(database)
    store.acquire(target['id'],'b')
    path = tmp_path/'deferred.claim.json'
    result = call('notifications','claim','--notice',notice['id'],'--actor','a','--claim-file',path)
    assert result['state'] == 'deferred' and result['message_sent'] is False
    assert 'claim_token' not in json.loads(path.read_text(encoding='utf-8'))['claim']
    call('notifications','ack','--claim-file',path,'--outcome','delivered','--receipt-thread-id','b',ok=False)
    assert call('notifications','archive','--notice',notice['id'],'--actor','a')['state'] == 'obsolete'


def process(database, *args, stdin=None):
    return subprocess.run([sys.executable,'-B',str(PLUGIN/'scripts/coordinate.py'),'--db',str(database),*map(str,args)],
                          input=stdin,encoding='utf-8',capture_output=True,timeout=30)


def test_subprocess_utf8_stdin_and_real_foreground_release(tmp_path):
    database = tmp_path/'进度.sqlite3'
    def call(*args, stdin=None):
        result = process(database,*args,stdin=stdin)
        assert result.returncode == 0, result.stderr
        assert not result.stderr
        return json.loads(result.stdout)
    for chat in ('a','b'):
        call('register-chat','--chat',chat,'--label','测试'+chat,'--project-key','test')
        call('notifications','configure','--chat',chat,'--enable','--authorization-reference','synthetic scope')
    report = dict(chat_id='a',reporter='a',work_state='working',summary='中文管道输入',expected_revision=0)
    call('report-status','--input','-',stdin='\ufeff'+json.dumps(report,ensure_ascii=False))
    assert call('board')['chats'][0]['summary'] == '中文管道输入'
    requests = [call('request','--owner',actor,'--purpose','foreground','--resources',json.dumps(RESOURCE)) for actor in ('a','b')]
    run = call('run','--request',requests[0]['id'],'--owner','a','--tracking','contained' if os.name == 'nt' else 'observed','--',sys.executable,'-B','-c','pass')
    assert run['request_id'] == requests[0]['id'] and run['release_handoff']['pending_count'] == 1
    assert call('status','--request',requests[0]['id'])['state'] == 'completed'
    outbox = call('notifications','list','--actor','a')
    assert len(outbox['notices']) == 1 and outbox['notices'][0]['eligible_now']
    assert call('status','--request',requests[1]['id'])['state'] == 'waiting'


def test_separate_cli_dispatchers_claim_only_once(tmp_path):
    database = tmp_path/'race.sqlite3'
    _,_,_,notice = pending_notice(database)
    def contend(actor):
        return process(database,'notifications','claim','--notice',notice['id'],'--actor',actor,'--claim-file',tmp_path/(actor+'.claim.json'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contend,('a','c')))
    assert sorted(r.returncode for r in results) == [0,1]
    successful = json.loads(next(r.stdout for r in results if r.returncode == 0))
    assert successful['state'] == 'sending' and 'claim_token' not in successful
