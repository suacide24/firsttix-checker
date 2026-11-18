"""Telegram-routing tests for firsttix-checker. The Telegram API call is mocked;
no network is used. Run: python -m unittest tests.test_telegram -v"""
import os
import sys
import unittest
from unittest import mock

# firsttix_checker parses CLI args at import time — give it a clean argv.
sys.argv = ["test"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import firsttix_checker as ft  # noqa: E402


def show(name="Aja Monet", date="Sat, Nov 21", link="https://1sttix.org/e/1", info_url="", rare=False):
    return {"source": "1stTix", "name": name, "date": date, "link": link,
            "info_url": info_url, "rare": rare}


class FakePost:
    """Stands in for requests.post; records payloads, returns a Telegram-shaped body."""
    def __init__(self, ok=True, message_id=55):
        self.ok, self.message_id, self.payloads = ok, message_id, []

    def __call__(self, url, json=None, timeout=None):
        self.payloads.append(json)
        body = ({"ok": True, "result": {"message_id": self.message_id}}
                if self.ok else {"ok": False, "description": "nope"})
        return mock.Mock(status_code=200, json=mock.Mock(return_value=body))


class TelegramTests(unittest.TestCase):
    def test_no_token_means_no_network_call(self):
        with mock.patch.object(ft, "TELEGRAM_BOT_TOKEN", ""):
            with mock.patch.object(ft.requests, "post") as post:
                self.assertIsNone(ft._tg_call("sendMessage", {"a": 1}))
                post.assert_not_called()

    def test_send_targets_the_project_topic(self):
        fp = FakePost()
        with mock.patch.object(ft, "TELEGRAM_BOT_TOKEN", "123:abc"), \
                mock.patch.object(ft.requests, "post", fp):
            self.assertEqual(ft.send_telegram("hi", ("Open", "https://x")), 55)
        p = fp.payloads[0]
        self.assertEqual(p["message_thread_id"], 21)
        self.assertEqual(p["chat_id"], -1003983050734)
        self.assertEqual(p["parse_mode"], "HTML")
        self.assertTrue(p["disable_web_page_preview"])
        self.assertEqual(p["reply_markup"]["inline_keyboard"][0][0]["url"], "https://x")

    def test_alert_goes_to_telegram_not_email(self):
        fp = FakePost()
        with mock.patch.object(ft, "TELEGRAM_BOT_TOKEN", "123:abc"), \
                mock.patch.object(ft.requests, "post", fp), \
                mock.patch.object(ft, "send_email_notification") as email:
            self.assertTrue(ft.deliver_owner_alert([show()]))
        email.assert_not_called()
        self.assertEqual(fp.payloads[0]["message_thread_id"], 21)

    def test_telegram_failure_falls_back_to_email(self):
        fp = FakePost(ok=False)
        with mock.patch.object(ft, "TELEGRAM_BOT_TOKEN", "123:abc"), \
                mock.patch.object(ft.requests, "post", fp), \
                mock.patch.object(ft, "send_email_notification", return_value=True) as email:
            self.assertTrue(ft.deliver_owner_alert([show()]))
        email.assert_called_once()

    def test_no_telegram_configured_uses_email(self):
        with mock.patch.object(ft, "TELEGRAM_BOT_TOKEN", ""), \
                mock.patch.object(ft, "send_email_notification", return_value=True) as email:
            self.assertTrue(ft.deliver_owner_alert([show()]))
        email.assert_called_once()

    def test_first_line_says_what_is_new_and_text_is_escaped(self):
        text, button = ft.build_telegram_message(
            ft.group_shows_by_name([show(name="Tom & <b>X</b>")])
        )
        first = text.splitlines()[0]
        self.assertTrue(first.startswith("<b>🎭"))
        self.assertIn("Tom &amp; &lt;b&gt;X&lt;/b&gt;", text)
        self.assertEqual(button, ("🎟️ Open show", "https://1sttix.org/e/1"))

    def test_long_lists_stay_under_the_limit(self):
        many = [show(name=f"Show {i}", link=f"https://1sttix.org/e/{i}") for i in range(300)]
        text, _ = ft.build_telegram_message(ft.group_shows_by_name(many))
        self.assertLessEqual(len(text), ft.TELEGRAM_MAX_CHARS)
        self.assertIn("more on the site", text)

    def test_failures_never_log_the_token(self):
        logs = []

        def boom(*a, **k):
            raise RuntimeError("POST https://api.telegram.org/bot123:SECRET/sendMessage failed")

        with mock.patch.object(ft, "TELEGRAM_BOT_TOKEN", "123:SECRET"), \
                mock.patch.object(ft.requests, "post", boom), \
                mock.patch.object(ft, "log_message", lambda m: logs.append(m)):
            self.assertIsNone(ft._tg_call("sendMessage", {"a": 1}))
        self.assertTrue(logs)
        self.assertFalse(any("SECRET" in m for m in logs))


if __name__ == "__main__":
    unittest.main()
