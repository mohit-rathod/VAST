"""Optional real-Chromium UI acceptance check with an offline model and temp DB.

Run: VAST_TEST_STUB_OPENAI=1 python -m scripts.verify_chat_ui --chromium /usr/bin/chromium
Requires the optional playwright Python package and a Chromium installation.
Network requests are intercepted; SMTP and live model calls are forbidden.
"""
from contextlib import closing
from datetime import datetime, timedelta
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
if os.getenv('VAST_TEST_STUB_OPENAI') == '1':
    sdk = types.ModuleType('openai')
    class UnavailableOpenAI:
        def __init__(self, *args, **kwargs):
            raise AssertionError('Live model calls are forbidden in this UI check')
    sdk.OpenAI = UnavailableOpenAI
    sys.modules['openai'] = sdk

from playwright.sync_api import sync_playwright
from app import db
from agents.nextdim.agent import NextDimAgent
from helpers import INTAKE, COMPLAINT, ScriptedClient
from services.date_shortcuts import date_shortcuts
from tools import available_slots as calendar


class NeverEmail:
    def issue(self, *args, **kwargs):
        raise AssertionError('No email may be sent')
    def verify(self, *args, **kwargs):
        raise AssertionError('No email verification may run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium', default=None)
    parser.add_argument('--out', type=Path, default=Path('artifacts/ui-v0.2.1'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    os.environ['VAST_REQUIRE_EMAIL_VERIFICATION'] = 'false'
    zone = ZoneInfo('America/New_York')
    moment = datetime(2026, 9, 28, 10, 0, tzinfo=zone)
    calendar.FIRST_DAY, calendar.DAYS = None, 14
    calendar.now = lambda z=None: moment.astimezone(z or zone)
    html = (ROOT / 'app/static/index.html').read_text()
    js = (ROOT / 'app/static/chat-actions.js').read_text()
    results, errors, agents = {}, [], []

    with tempfile.TemporaryDirectory() as directory, sync_playwright() as playwright:
        db.DB_PATH = Path(directory) / 'ui.db'
        db.init_db()
        with closing(db.connect()) as conn, conn:
            conn.executemany('INSERT INTO clinics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
                (1, 'Clinic A', 'ENT', 'A Street', 'New York', 'NY', '10001', 40.7549, -73.9844),
                (2, 'Clinic B', 'ENT', 'B Street', 'New York', 'NY', '11215', 40.6724, -73.9778),
            ])
            conn.execute('INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (1, 'Test', 'Patient', 'test@example.test', '+12125550100', None,
                          'Home Street', 'New York', 'NY', '10001', 40.7549, -73.9844, 'Ear trouble'))
        kwargs = {'headless': True}
        if args.chromium:
            kwargs['executable_path'] = args.chromium
        browser = playwright.chromium.launch(**kwargs)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.clock.install(time=moment)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def request(path, options):
            if path == '/api/config':
                data = {'model': 'offline scripted model', 'ready': True}
            elif path == '/api/reset':
                agent = NextDimAgent(client=ScriptedClient(INTAKE, COMPLAINT, {'intent': 'confirm'}),
                                     verification=NeverEmail())
                agents.append(agent)
                data = {'session_id': f'ui-{len(agents)}', 'reply': agent.start()}
            elif path == '/api/chat':
                payload = json.loads(options.get('body', '{}'))
                agent = agents[-1]
                events = []
                agent.on_event = events.append
                reply = agent.handle(payload['message'])
                data = {'session_id': f'ui-{len(agents)}', 'reply': reply, 'step': agent.step,
                        'done': agent.flow.finished, 'booking': agent.booking,
                        'bookings': agent.booking_history, 'actions': agent.actions,
                        'events': events}
            else:
                return {'status': 404, 'body': {'detail': 'Not found'}}
            return {'status': 200, 'body': json.loads(json.dumps(data, default=str))}

        # In-memory transport also works in locked-down browsers that disallow
        # navigation. It invokes the real agent but performs no HTTP networking.
        page.expose_function('__vastRequest', request)
        bridge = """<script>
        window.fetch = async (path, options = {}) => {
            const result = await window.__vastRequest(path, options);
            return new Response(JSON.stringify(result.body), {
                status: result.status, headers: {'Content-Type': 'application/json'}
            });
        };
        </script>"""
        document = html.replace('<script src="/static/chat-actions.js"></script>',
                                '<script>' + js + '</script>' + bridge)
        page.set_content(document)
        page.get_by_text('Welcome to the NextDim Health portal.', exact=False).wait_for()
        assert '10-digit' not in page.locator('#log').inner_text()
        page.locator('#input').fill('Test Patient, test@example.test, 2125550100')
        page.locator('#send').click()
        page.get_by_role('button', name='Details are correct', exact=True).click()
        page.get_by_role('button', name='Book an appointment', exact=True).click()
        page.locator('#input').fill('My ear is sore')
        page.locator('#send').click()
        page.get_by_role('button', name='Yes, that is correct', exact=True).click()
        page.get_by_role('button', name='Today - Monday 2026-09-28', exact=True).wait_for()
        assert page.locator('.action-group-date button').count() == 7
        page.wait_for_function('!busy')
        page.screenshot(path=str(args.out / 'date-shortcuts-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_function('(() => { const p = document.querySelector("main"); return p.scrollHeight - p.scrollTop - p.clientHeight < 2; })()')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(args.out / 'date-shortcuts-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1280, 'height': 900})
        page.get_by_role('button', name='Tomorrow - Tuesday 2026-09-29', exact=True).click()
        page.locator('.action-group-slot button').first.wait_for()
        page.locator('.action-group-slot button').nth(1).click()
        page.get_by_role('button', name='Confirm booking', exact=True).wait_for()
        selected = agents[-1].flow.chosen
        page.screenshot(path=str(args.out / 'confirm-booking.png'), full_page=True)
        page.locator('#input').fill('I confirm this slot')
        page.locator('#send').click()
        page.get_by_text('This chat is now closed.', exact=False).wait_for()
        page.wait_for_function('closed && !busy')
        assert page.locator('#actions button').count() == 0
        assert page.locator('#endBtn').is_disabled()
        assert page.locator('#resetBtn').is_enabled()
        assert agents[-1].booking['clinic_id'] == selected.clinic_id
        assert agents[-1].booking['slot_date'] == '2026-09-29'
        with closing(db.connect()) as conn, conn:
            assert conn.execute('SELECT count(*) FROM bookings').fetchone()[0] == 1
        results['complete_chat_click_and_natural_confirmation'] = 'passed'
        results['responsive_layout_no_horizontal_overflow'] = 'passed'
        results['booked_chat_disables_controls'] = 'passed'

        page.locator('#resetBtn').click()
        page.locator('#endBtn').click()
        page.get_by_role('button', name='No, continue', exact=True).click()
        assert not agents[-1].flow.finished
        page.locator('#endBtn').click()
        page.get_by_role('button', name='Yes, end chat', exact=True).click()
        page.get_by_text('without creating', exact=False).last.wait_for()
        assert agents[-1].flow.finished and agents[-1].booking is None
        results['end_chat_confirmation_continue_and_end'] = 'passed'

        # Isolated action clock test: idle tabs cannot submit an expired Today.
        clock_page = browser.new_page()
        clock_page.on('pageerror', lambda error: errors.append(str(error)))
        before_noon = datetime(2026, 9, 28, 11, 59, 59, tzinfo=zone)
        clock_page.clock.install(time=before_noon)
        clock_page.set_content('<div id="actions"></div>')
        clock_page.add_script_tag(content=js)
        shortcuts = date_shortcuts(before_noon, [before_noon.date() + timedelta(days=n) for n in range(8)])
        clock_page.evaluate('''actions => {
            window.sent = [];
            window.renderer = new ChatActionRenderer(document.getElementById('actions'), message => sent.push(message), () => false);
            renderer.render(actions);
        }''', shortcuts)
        clock_page.get_by_role('button', name='Today - Monday 2026-09-28', exact=True).wait_for()
        clock_page.clock.run_for(2000)
        assert clock_page.get_by_role('button', name='Today - Monday 2026-09-28', exact=True).count() == 0
        assert clock_page.get_by_role('button', name='Tomorrow - Tuesday 2026-09-29', exact=True).count() == 1
        results['today_expires_without_a_new_chat_turn_at_noon'] = 'passed'
        clock_page.clock.set_system_time(datetime(2026, 9, 29, 0, 0, tzinfo=zone))
        clock_page.clock.run_for(1000)
        clock_page.get_by_role('button', name='Today - Tuesday 2026-09-29', exact=True).click()
        assert clock_page.evaluate('sent') == ['2026-09-29']
        results['midnight_label_refresh_keeps_absolute_payload'] = 'passed'
        clock_page.evaluate('renderer.render([{label: "<img src=x onerror=alert(1)>", message:"1"}])')
        assert clock_page.locator('#actions img').count() == 0
        results['labels_are_text_not_html'] = 'passed'
        assert not errors, errors
        results['browser_javascript_errors'] = errors
        browser.close()

    (args.out / 'verification.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()