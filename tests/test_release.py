"""Verify release privacy defaults without authorizing accounts or uploading."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import channel_config


class ReleaseTests(unittest.TestCase):
    def test_dashboard_channel_endpoint_is_distributed(self):
        endpoint = channel_config.ROOT / 'dashboard/app/api/channels/route.js'
        self.assertTrue(endpoint.is_file(), 'Channel controls require the channels API route.')

    def test_new_profile_has_no_connection_or_enabled_schedule(self):
        with tempfile.TemporaryDirectory(dir=channel_config.ROOT / 'output') as directory:
            root = Path(directory)
            with patch.object(channel_config, 'ROOT', root), patch.object(channel_config, 'CHANNELS', root / 'channels'):
                profile = channel_config.create_channel('main', 'Main channel')
                self.assertIsNone(profile['youtube_channel_id'])
                self.assertFalse(profile['schedule']['enabled'])

    def test_sign_in_uploads_are_gone_and_review_is_on(self):
        self.assertFalse((channel_config.ROOT / 'startup_upload.py').exists())
        self.assertTrue(channel_config.CHANNEL_DEFAULTS['require_review'])


if __name__ == '__main__':
    unittest.main()
