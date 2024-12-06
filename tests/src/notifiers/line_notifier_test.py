from __future__ import annotations

import os
import subprocess
import unittest
from io import BytesIO
from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np
from PIL import Image

from src.notifiers.line_notifier import LineNotifier
from src.notifiers.line_notifier import main


class TestLineNotifier(unittest.IsolatedAsyncioTestCase):
    """
    Unit tests for the LineNotifier class methods.
    """

    def setUp(self) -> None:
        """
        Set up method to initialise test variables and LineNotifier instance.
        """
        self.line_token: str = 'test_token'
        self.message: str = 'Test Message'
        self.image: np.ndarray = np.zeros((100, 100, 3), dtype=np.uint8)
        self.notifier: LineNotifier = LineNotifier()

    @patch.dict('os.environ', {'LINE_NOTIFY_TOKEN': 'test_env_token'})
    @patch('aiohttp.ClientSession.post')
    async def test_init_with_env_token(self, mock_post: MagicMock) -> None:
        """
        Test case for sending a notification using an environment token.
        """
        # Mock the response from aiohttp.ClientSession.post
        mock_response: MagicMock = MagicMock()
        mock_response.status = 200  # Simulate a successful request
        mock_post.return_value.__aenter__.return_value = mock_response

        notifier: LineNotifier = LineNotifier()
        status_code: int = await notifier.send_notification(self.message)

        # Assert that the status code is 200
        self.assertEqual(status_code, 200)
        mock_post.assert_called_once_with(
            'https://notify-api.line.me/api/notify',
            headers={'Authorization': 'Bearer test_env_token'},
            params={'message': self.message},
            data=None,
        )

    async def test_init_without_token(self) -> None:
        """
        Test case for sending a notification without a token
        (expects ValueError).
        """
        with self.assertRaises(ValueError):
            await self.notifier.send_notification(
                self.message,
                line_token=None,
            )

    @patch('aiohttp.ClientSession.post')
    async def test_send_notification_without_image(
        self,
        mock_post: MagicMock,
    ) -> None:
        """
        Test case for sending notification without an image.
        """
        mock_response: MagicMock = MagicMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response

        status_code: int = await self.notifier.send_notification(
            self.message, line_token=self.line_token,
        )
        self.assertEqual(status_code, 200)
        mock_post.assert_called_once_with(
            'https://notify-api.line.me/api/notify',
            headers={'Authorization': f'Bearer {self.line_token}'},
            params={'message': self.message},
            data=None,
        )

    @patch('aiohttp.ClientSession.post')
    async def test_send_notification_with_image(
        self, mock_post: MagicMock,
    ) -> None:
        """
        Test case for sending notification with an image as a NumPy array.
        """
        mock_response: MagicMock = MagicMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response

        status_code: int = await self.notifier.send_notification(
            self.message,
            self.image,
            line_token=self.line_token,
        )
        self.assertEqual(status_code, 200)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn('data', kwargs)
        self.assertIn('imageFile', kwargs['data'])

        # 檢查 imageFile
        image_file = kwargs['data']['imageFile']
        self.assertEqual(image_file.name, 'image.png')
        self.assertEqual(image_file.content_type, 'image/png')
        image_file.seek(0)
        image: Image.Image = Image.open(image_file)
        self.assertTrue(np.array_equal(np.array(image), self.image))

    @patch('aiohttp.ClientSession.post')
    async def test_send_notification_with_bytes_image(
        self,
        mock_post: MagicMock,
    ) -> None:
        """
        Test case for sending notification
            with an image as bytes (e.g., BytesIO).
        """
        mock_response: MagicMock = MagicMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response

        buffer: BytesIO = BytesIO()
        Image.fromarray(self.image).save(buffer, format='PNG')
        buffer.seek(0)
        image_bytes: bytes = buffer.read()

        status_code: int = await self.notifier.send_notification(
            self.message, image_bytes, line_token=self.line_token,
        )
        self.assertEqual(status_code, 200)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn('data', kwargs)
        self.assertIn('imageFile', kwargs['data'])

        # Check if the image is correctly converted and sent
        image_file = kwargs['data']['imageFile']
        self.assertEqual(image_file.name, 'image.png')
        self.assertEqual(image_file.content_type, 'image/png')
        image: Image.Image = Image.open(image_file)
        self.assertTrue(np.array_equal(np.array(image), self.image))

    @patch('aiohttp.ClientSession.post')
    async def test_main(self, mock_post: MagicMock) -> None:
        """
        Test the main function to ensure the complete process is covered.
        """
        mock_response: MagicMock = MagicMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response

        with patch('builtins.print') as mock_print:
            await main()
            mock_print.assert_called_once_with('Response code: 200')

    @patch.dict(os.environ, {'LINE_NOTIFY_TOKEN': 'test_token'})
    @patch('aiohttp.ClientSession.post')
    async def test_main_as_script(self, mock_post: MagicMock) -> None:
        mock_response: MagicMock = MagicMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response

        # Get the absolute path to the line_notifier.py script
        script_path = os.path.abspath(
            os.path.join(
                os.path.dirname(
                    __file__,
                ), '../../../src/notifiers/line_notifier.py',
            ),
        )

        # Run the script using subprocess
        result = subprocess.run(
            ['python', script_path],
            capture_output=True, text=True,
        )

        # Print stderr and stdout for debugging
        print('STDOUT:', result.stdout)
        print('STDERR:', result.stderr)

        # Assert that the script runs without errors
        self.assertEqual(
            result.returncode, 0,
            'Script exited with a non-zero status.',
        )


if __name__ == '__main__':
    unittest.main()
