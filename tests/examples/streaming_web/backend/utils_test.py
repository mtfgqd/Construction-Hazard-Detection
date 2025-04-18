from __future__ import annotations

import base64
import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import WebSocket

from examples.streaming_web.backend.utils import Utils


class TestUtils(unittest.IsolatedAsyncioTestCase):
    """
    Test suite for utility functions in Utils.
    """

    async def test_encode(self) -> None:
        """
        Test the encode function to ensure it encodes correctly.
        """
        input_string = 'test_label'
        encoded_string = Utils.encode(input_string)
        expected_encoded = base64.urlsafe_b64encode(
            input_string.encode('utf-8'),
        ).decode('utf-8')
        self.assertEqual(encoded_string, expected_encoded)

    async def test_is_base64(self) -> None:
        """
        Test the is_base64 function for different cases.
        """
        valid_base64 = 'QmFzZTY0U3RyaW5n'  # Base64 for "Base64String"
        invalid_base64 = 'NotBase64@#%'
        empty_string = ''

        self.assertTrue(Utils.is_base64(valid_base64))
        self.assertFalse(Utils.is_base64(invalid_base64))
        self.assertFalse(Utils.is_base64(empty_string))

    async def test_decode_valid_base64(self) -> None:
        """
        Test the decode function with valid Base64 input.
        """
        original = 'test_label'
        encoded = base64.urlsafe_b64encode(
            original.encode('utf-8'),
        ).decode('utf-8')
        decoded = Utils.decode(encoded)
        self.assertEqual(decoded, original)

    async def test_decode_invalid_base64(self) -> None:
        """
        Test the decode function with invalid Base64 input.
        """
        invalid = 'Invalid_String!'
        # This should raise an exception or return the input unchanged
        # depending on the implementation of the decode function.
        decoded = Utils.decode(invalid)
        self.assertEqual(decoded, invalid)

    async def test_send_frames(self) -> None:
        """
        Test the send_frames function to ensure it sends the correct data.
        """
        # Mock the WebSocket object
        # and its send_json method
        websocket_mock = MagicMock(spec=WebSocket)
        websocket_mock.send_json = AsyncMock()

        label = 'label1'
        updated_data = [
            {'key': 'image1', 'image': 'encoded_image_data_1'},
            {'key': 'image2', 'image': 'encoded_image_data_2'},
        ]
        await Utils.send_frames(websocket_mock, label, updated_data)
        expected_data = {
            'label': label,
            'images': updated_data,
        }
        websocket_mock.send_json.assert_awaited_once_with(expected_data)


if __name__ == '__main__':
    unittest.main()

'''
pytest \
    --cov=examples.streaming_web.backend.utils \
    --cov-report=term-missing \
    tests/examples/streaming_web/backend/utils_test.py
'''
