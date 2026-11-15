import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace

from src.handlers.telegram_handlers import (
    format_bytes,
    format_speed,
    format_eta,
    format_progress_bar,
    format_state,
    escape_md,
    build_torrents_list_message,
    build_torrent_detail_message,
    build_delete_confirm_message,
    status_handler,
    pause_all_handler,
    resume_all_handler,
    qbt_action_callback,
    start_handler,
)
import src.services.qbittorrent_service as qbt_svc


def make_sample_torrent(name="Inception (2010)", hash_id="4a5b6c7d8e9f0123456789abcdef0123456789ab", state="downloading"):
    return SimpleNamespace(
        hash=hash_id,
        name=name,
        state=state,
        progress=0.452,
        size=4500000000,
        total_size=4500000000,
        downloaded=2034000000,
        uploaded=150000000,
        dlspeed=3500000,
        upspeed=120000,
        eta=700,
        num_seeds=45,
        num_complete=130,
        num_leechs=8,
        num_incomplete=40,
        ratio=0.07,
        added_on=1700000000,
        save_path="/Downloads/Movies",
    )


class TestFormattingHelpers(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(None), "0 B")
        self.assertEqual(format_bytes(-50), "0 B")
        self.assertEqual(format_bytes(512), "512.0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 150), "150.0 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 2.5), "2.5 GB")

    def test_format_speed(self):
        self.assertEqual(format_speed(0), "0 B/s")
        self.assertEqual(format_speed(1024 * 1024 * 5), "5.0 MB/s")

    def test_format_eta(self):
        self.assertEqual(format_eta(None), "∞")
        self.assertEqual(format_eta(-1), "∞")
        self.assertEqual(format_eta(8640000), "∞")
        self.assertEqual(format_eta(45), "45s")
        self.assertEqual(format_eta(125), "2m 5s")
        self.assertEqual(format_eta(3665), "1h 1m")
        self.assertEqual(format_eta(90000), "1d 1h")

    def test_format_progress_bar(self):
        self.assertEqual(format_progress_bar(0.0, length=8), "▱▱▱▱▱▱▱▱")
        self.assertEqual(format_progress_bar(1.0, length=8), "▰▰▰▰▰▰▰▰")
        self.assertEqual(format_progress_bar(0.5, length=8), "▰▰▰▰▱▱▱▱")

    def test_format_state(self):
        label, is_paused = format_state("downloading")
        self.assertEqual(label, "⬇️ Downloading")
        self.assertFalse(is_paused)

        label, is_paused = format_state("pausedDL")
        self.assertEqual(label, "⏸️ Paused (DL)")
        self.assertTrue(is_paused)

        label, is_paused = format_state("uploading")
        self.assertEqual(label, "⬆️ Seeding")
        self.assertFalse(is_paused)

        label, is_paused = format_state("stoppedUP")
        self.assertEqual(label, "⏸️ Stopped (UP)")
        self.assertTrue(is_paused)

        label, is_paused = format_state("someUnknownState")
        self.assertEqual(label, "Someunknownstate")
        self.assertFalse(is_paused)

    def test_escape_md(self):
        self.assertEqual(escape_md("Movie_Title [2024] *HD*"), "Movie\\_Title \\[2024\\] \\*HD\\*")


class TestViewBuilders(unittest.TestCase):
    def setUp(self):
        self.sample_torrent = make_sample_torrent()

    def test_empty_torrents_list(self):
        text, markup = build_torrents_list_message([], page=1)
        self.assertIn("No torrents found", text)
        self.assertEqual(len(markup.inline_keyboard), 1)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "qbt:l:1")

    def test_torrents_list_with_items_and_pagination(self):
        # 12 torrents => 3 pages with default page size of 5
        torrents = [make_sample_torrent(name=f"Movie {i}", hash_id=f"hash{i:036d}") for i in range(12)]
        transfer_info = SimpleNamespace(dl_info_speed=3500000, up_info_speed=120000)
        
        # Page 1
        text1, markup1 = build_torrents_list_message(torrents, page=1, transfer_info=transfer_info)
        self.assertIn("Page 1/3", text1)
        self.assertIn("Movie 0", text1)
        # Should have 5 torrent buttons + 1 nav row + 1 global actions row = 7 rows
        self.assertEqual(len(markup1.inline_keyboard), 7)
        nav_row = markup1.inline_keyboard[5]
        self.assertEqual(nav_row[0].callback_data, "qbt:noop")  # No prev on page 1
        self.assertEqual(nav_row[1].text, "1/3")
        self.assertEqual(nav_row[2].callback_data, "qbt:l:2")  # Next page

        # Page 2
        text2, markup2 = build_torrents_list_message(torrents, page=2, transfer_info=transfer_info)
        self.assertIn("Page 2/3", text2)
        nav_row2 = markup2.inline_keyboard[5]
        self.assertEqual(nav_row2[0].callback_data, "qbt:l:1")  # Prev page
        self.assertEqual(nav_row2[2].callback_data, "qbt:l:3")  # Next page

        # Page 3 (2 items)
        text3, markup3 = build_torrents_list_message(torrents, page=3, transfer_info=transfer_info)
        self.assertIn("Page 3/3", text3)
        self.assertEqual(len(markup3.inline_keyboard), 4)  # 2 torrent buttons + nav + global

    def test_torrent_detail_message_downloading(self):
        text, markup = build_torrent_detail_message(self.sample_torrent)
        self.assertIn("Inception", text)
        self.assertIn("45.2%", text)
        # Torrent is downloading, so button should be Pause
        self.assertEqual(markup.inline_keyboard[0][0].text, "⏸️ Pause / Stop")
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "qbt:p:4a5b6c7d8e9f")
        # Discard button
        self.assertEqual(markup.inline_keyboard[1][0].callback_data, "qbt:da:4a5b6c7d8e9f")
        # Back to list
        self.assertEqual(markup.inline_keyboard[2][0].callback_data, "qbt:l:1")

    def test_torrent_detail_message_paused(self):
        paused_torrent = SimpleNamespace(**vars(self.sample_torrent))
        paused_torrent.state = "pausedDL"
        text, markup = build_torrent_detail_message(paused_torrent)
        # Torrent is paused, button should be Resume
        self.assertEqual(markup.inline_keyboard[0][0].text, "▶️ Resume / Start")
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "qbt:r:4a5b6c7d8e9f")

    def test_delete_confirm_message(self):
        text, markup = build_delete_confirm_message(self.sample_torrent)
        self.assertIn("Are you sure you want to delete", text)
        # Keep files button
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "qbt:dk:4a5b6c7d8e9f")
        # Delete with files button
        self.assertEqual(markup.inline_keyboard[0][1].callback_data, "qbt:df:4a5b6c7d8e9f")
        # Cancel button
        self.assertEqual(markup.inline_keyboard[1][0].callback_data, "qbt:v:4a5b6c7d8e9f")


class TestQbittorrentService(unittest.IsolatedAsyncioTestCase):
    @patch("src.services.qbittorrent_service.qbt_client")
    @patch("src.services.qbittorrent_service.ensure_qbt_login", return_value=True)
    async def test_get_torrents_info(self, mock_login, mock_client):
        mock_client.torrents_info.return_value = ["torrent1", "torrent2"]
        res = await qbt_svc.get_torrents_info()
        self.assertEqual(res, ["torrent1", "torrent2"])
        mock_client.torrents_info.assert_called_once()

    @patch("src.services.qbittorrent_service.qbt_client")
    @patch("src.services.qbittorrent_service.ensure_qbt_login", return_value=True)
    async def test_get_torrent_info(self, mock_login, mock_client):
        mock_client.torrents_info.return_value = ["torrent1"]
        res = await qbt_svc.get_torrent_info("hash123")
        self.assertEqual(res, "torrent1")

    @patch("src.services.qbittorrent_service.qbt_client")
    @patch("src.services.qbittorrent_service.ensure_qbt_login", return_value=True)
    async def test_get_torrent_by_short_hash(self, mock_login, mock_client):
        t1 = SimpleNamespace(hash="aabbccdd11223344")
        t2 = SimpleNamespace(hash="1122334455667788")
        mock_client.torrents_info.return_value = [t1, t2]

        found = await qbt_svc.get_torrent_by_short_hash("aabbcc")
        self.assertEqual(found, t1)

        found_case_insensitive = await qbt_svc.get_torrent_by_short_hash("AABBCC")
        self.assertEqual(found_case_insensitive, t1)

        not_found = await qbt_svc.get_torrent_by_short_hash("999999")
        self.assertIsNone(not_found)

    @patch("src.services.qbittorrent_service.qbt_client")
    @patch("src.services.qbittorrent_service.ensure_qbt_login", return_value=True)
    async def test_pause_and_resume_torrents(self, mock_login, mock_client):
        await qbt_svc.pause_torrents("all")
        mock_client.torrents_pause.assert_called_once_with(torrent_hashes="all")

        await qbt_svc.resume_torrents("hash123")
        mock_client.torrents_resume.assert_called_once_with(torrent_hashes="hash123")

    @patch("src.services.qbittorrent_service.qbt_client")
    @patch("src.services.qbittorrent_service.ensure_qbt_login", return_value=True)
    async def test_delete_torrents(self, mock_login, mock_client):
        await qbt_svc.delete_torrents("hash123", delete_files=True)
        mock_client.torrents_delete.assert_called_once_with(delete_files=True, torrent_hashes="hash123")

    @patch("src.services.qbittorrent_service.qbt_client")
    @patch("src.services.qbittorrent_service.ensure_qbt_login", return_value=True)
    async def test_get_transfer_info(self, mock_login, mock_client):
        mock_client.transfer_info.return_value = {"dl_info_speed": 1024}
        res = await qbt_svc.get_transfer_info()
        self.assertEqual(res, {"dl_info_speed": 1024})


class TestTelegramCallbacks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.torrent = make_sample_torrent()

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.get_torrent_by_short_hash")
    @patch("src.handlers.telegram_handlers.pause_torrents", new_callable=AsyncMock)
    async def test_pause_callback(self, mock_pause, mock_get, mock_auth):
        mock_get.return_value = self.torrent

        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = "qbt:p:4a5b6c7d8e9f"
        context = MagicMock()

        await qbt_action_callback(update, context)

        mock_pause.assert_called_once_with(self.torrent.hash)
        update.callback_query.answer.assert_called_with("⏸️ Torrent paused.")

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.get_torrent_by_short_hash")
    @patch("src.handlers.telegram_handlers.resume_torrents", new_callable=AsyncMock)
    async def test_resume_callback(self, mock_resume, mock_get, mock_auth):
        mock_get.return_value = self.torrent

        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = "qbt:r:4a5b6c7d8e9f"
        context = MagicMock()

        await qbt_action_callback(update, context)

        mock_resume.assert_called_once_with(self.torrent.hash)
        update.callback_query.answer.assert_called_with("▶️ Torrent resumed.")

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.get_torrent_by_short_hash")
    @patch("src.handlers.telegram_handlers.delete_torrents", new_callable=AsyncMock)
    @patch("src.handlers.telegram_handlers.get_torrents_info", new_callable=AsyncMock, return_value=[])
    @patch("src.handlers.telegram_handlers.get_transfer_info", new_callable=AsyncMock, return_value=None)
    async def test_delete_keep_files_callback(self, mock_transfer, mock_list, mock_del, mock_get, mock_auth):
        mock_get.return_value = self.torrent

        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = "qbt:dk:4a5b6c7d8e9f"
        context = MagicMock()

        await qbt_action_callback(update, context)

        mock_del.assert_called_once_with(self.torrent.hash, delete_files=False)
        update.callback_query.answer.assert_called_with("🗑️ Torrent removed (files kept on disk).", show_alert=True)

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.get_torrent_by_short_hash")
    @patch("src.handlers.telegram_handlers.delete_torrents", new_callable=AsyncMock)
    @patch("src.handlers.telegram_handlers.get_torrents_info", new_callable=AsyncMock, return_value=[])
    @patch("src.handlers.telegram_handlers.get_transfer_info", new_callable=AsyncMock, return_value=None)
    async def test_delete_with_files_callback(self, mock_transfer, mock_list, mock_del, mock_get, mock_auth):
        mock_get.return_value = self.torrent

        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = "qbt:df:4a5b6c7d8e9f"
        context = MagicMock()

        await qbt_action_callback(update, context)

        mock_del.assert_called_once_with(self.torrent.hash, delete_files=True)
        update.callback_query.answer.assert_called_with("🔥 Torrent and files permanently deleted.", show_alert=True)

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.pause_torrents", new_callable=AsyncMock)
    @patch("src.handlers.telegram_handlers.get_torrents_info", new_callable=AsyncMock, return_value=[])
    @patch("src.handlers.telegram_handlers.get_transfer_info", new_callable=AsyncMock, return_value=None)
    async def test_pause_all_callback(self, mock_transfer, mock_list, mock_pause, mock_auth):
        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = "qbt:pa"
        context = MagicMock()

        await qbt_action_callback(update, context)

        mock_pause.assert_called_once_with("all")
        update.callback_query.answer.assert_called_with("⏸️ Paused all torrents.")

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.resume_torrents", new_callable=AsyncMock)
    @patch("src.handlers.telegram_handlers.get_torrents_info", new_callable=AsyncMock, return_value=[])
    @patch("src.handlers.telegram_handlers.get_transfer_info", new_callable=AsyncMock, return_value=None)
    async def test_resume_all_callback(self, mock_transfer, mock_list, mock_resume, mock_auth):
        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = "qbt:ra"
        context = MagicMock()

        await qbt_action_callback(update, context)

        mock_resume.assert_called_once_with("all")
        update.callback_query.answer.assert_called_with("▶️ Resumed all torrents.")

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.get_torrents_info", new_callable=AsyncMock)
    @patch("src.handlers.telegram_handlers.get_transfer_info", new_callable=AsyncMock, return_value=None)
    async def test_status_command(self, mock_transfer, mock_list, mock_auth):
        mock_list.return_value = [self.torrent]

        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()
        context.args = []

        await status_handler(update, context)

        update.message.reply_text.assert_called_once()
        args, kwargs = update.message.reply_text.call_args
        self.assertIn("Inception", args[0])

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.pause_torrents", new_callable=AsyncMock)
    async def test_pause_all_command(self, mock_pause, mock_auth):
        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()

        await pause_all_handler(update, context)

        mock_pause.assert_called_once_with("all")
        update.message.reply_text.assert_called_once_with("⏸️ All torrents have been paused.")

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=True)
    @patch("src.handlers.telegram_handlers.resume_torrents", new_callable=AsyncMock)
    async def test_resume_all_command(self, mock_resume, mock_auth):
        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()

        await resume_all_handler(update, context)

        mock_resume.assert_called_once_with("all")
        update.message.reply_text.assert_called_once_with("▶️ All torrents have been resumed.")

    @patch("src.handlers.telegram_handlers.is_authorized", new_callable=AsyncMock, return_value=False)
    async def test_unauthorized_user(self, mock_auth):
        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()

        await status_handler(update, context)
        update.message.reply_text.assert_called_once_with("Unauthorized access.")

        update.callback_query = AsyncMock()
        await qbt_action_callback(update, context)
        update.callback_query.answer.assert_called_once_with("Unauthorized access.", show_alert=True)


if __name__ == "__main__":
    unittest.main()
