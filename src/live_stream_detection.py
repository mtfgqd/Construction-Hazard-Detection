from __future__ import annotations

import argparse
import datetime
import gc
import os
import time
from pathlib import Path
from typing import TypedDict

import aiohttp
import anyio
import cv2
import numpy as np
from dotenv import load_dotenv
from sahi import AutoDetectionModel
from sahi.predict import get_sliced_prediction
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_fixed

load_dotenv()


class InputData(TypedDict):
    frame: np.ndarray
    model_key: str
    detect_with_server: bool


class DetectionData(TypedDict):
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    label: int


class LiveStreamDetector:
    """
    A class to perform live stream detection and tracking
    using YOLO with SAHI.
    """

    def __init__(
        self,
        api_url: str = 'http://localhost:5000',
        model_key: str = 'yolo11n',
        output_folder: str | None = None,
        detect_with_server: bool = False,
    ):
        """
        Initialises the LiveStreamDetector.

        Args:
            api_url (str): The URL of the API for detection.
            model_key (str): The model key for detection.
            output_folder (Optional[str]): Folder for detected frames.
        """
        self.api_url: str = (
            api_url if api_url.startswith('http') else f"http://{api_url}"
        )
        self.model_key: str = model_key
        self.output_folder: str | None = output_folder
        self.detect_with_server: bool = detect_with_server
        self.model: AutoDetectionModel | None = None
        self.access_token: str | None = None
        self.token_expiry: float = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(aiohttp.ClientError),
    )
    async def authenticate(self) -> None:
        """
        Authenticates with the API and retrieves the access token.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_url}/api/token",
                json={
                    'username': os.getenv('API_USERNAME'),
                    'password': os.getenv('API_PASSWORD'),
                },
            ) as response:
                response.raise_for_status()
                token_data = await response.json()
                if 'msg' in token_data:
                    raise Exception(token_data['msg'])
                elif 'access_token' in token_data:
                    self.access_token = token_data['access_token']
                else:
                    raise Exception(
                        "Token data does not contain 'msg' or 'access_token'",
                    )
                self.token_expiry = time.time() + 850

    def token_expired(self) -> bool:
        """
        Checks if the access token has expired.

        Returns:
            bool: True if the token has expired, False otherwise.
        """
        return time.time() >= self.token_expiry

    async def ensure_authenticated(self) -> None:
        """
        Ensures that the access token is valid and not expired.
        """
        if self.access_token is None or self.token_expired():
            await self.authenticate()

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(3),
        retry=retry_if_exception_type(aiohttp.ClientError),
    )
    async def generate_detections_cloud(
        self,
        frame: np.ndarray,
    ) -> list[list[float]]:
        """
        Sends the frame to the API for detection and retrieves the detections.

        Args:
            frame (cv2.Mat): The frame to send for detection.

        Returns:
            List[List[float]]: The detection data.
        """
        await self.ensure_authenticated()

        _, frame_encoded = cv2.imencode('.png', frame)
        frame_encoded_bytes = frame_encoded.tobytes()
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
        filename = f"frame_{timestamp}.png"

        headers = {'Authorization': f"Bearer {self.access_token}"}
        data = aiohttp.FormData()
        data.add_field(
            'image', frame_encoded_bytes,
            filename=filename, content_type='image/png',
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_url}/api/detect",
                data=data,
                params={'model': self.model_key},
                headers=headers,
            ) as response:
                response.raise_for_status()
                detections = await response.json()
                return detections

    async def generate_detections_local(
        self,
        frame: np.ndarray,
    ) -> list[list[float]]:
        """
        Generates detections locally using YOLO.

        Args:
            frame (np.ndarray): The frame to send for detection.

        Returns:
            List[List[float]]: The detection data.
        """
        if self.model is None:
            model_path = Path('models/pt/') / f"best_{self.model_key}.pt"
            self.model = AutoDetectionModel.from_pretrained(
                'yolo11',
                model_path=model_path,
                device='cuda:0',
            )

        result = get_sliced_prediction(
            frame,
            self.model,
            slice_height=376,
            slice_width=376,
            overlap_height_ratio=0.3,
            overlap_width_ratio=0.3,
        )

        # Compile detection data in YOLO format
        datas = []
        for object_prediction in result.object_prediction_list:
            label = int(object_prediction.category.id)
            x1, y1, x2, y2 = (
                int(x)
                for x in object_prediction.bbox.to_voc_bbox()
            )
            confidence = float(object_prediction.score.value)
            datas.append([x1, y1, x2, y2, confidence, label])

        # Remove overlapping labels for Hardhat and Safety Vest categories
        datas = self.remove_overlapping_labels(datas)

        # Remove fully contained Hardhat and Safety Vest labels
        datas = self.remove_completely_contained_labels(datas)

        return datas

    def remove_overlapping_labels(self, datas):
        """
        Removes overlapping labels for Hardhat and Safety Vest categories.

        Args:
            datas (list): A list of detection data in YOLO format.

        Returns:
            list: A list of detection data with overlapping labels removed.
        """
        hardhat_indices = [
            i for i, d in enumerate(
                datas,
            ) if d[5] == 0
        ]  # Indices of Hardhat detections
        # Indices of NO-Hardhat detections
        no_hardhat_indices = [i for i, d in enumerate(datas) if d[5] == 2]
        # Indices of Safety Vest detections
        safety_vest_indices = [i for i, d in enumerate(datas) if d[5] == 7]
        # Indices of NO-Safety Vest detections
        no_safety_vest_indices = [i for i, d in enumerate(datas) if d[5] == 4]

        to_remove = set()
        for hardhat_index in hardhat_indices:
            for no_hardhat_index in no_hardhat_indices:
                overlap = self.overlap_percentage(
                    datas[hardhat_index][:4], datas[no_hardhat_index][:4],
                )
                if overlap > 0.8:
                    to_remove.add(no_hardhat_index)

        for safety_vest_index in safety_vest_indices:
            for no_safety_vest_index in no_safety_vest_indices:
                overlap = self.overlap_percentage(
                    datas[safety_vest_index][:4],
                    datas[no_safety_vest_index][:4],
                )
                if overlap > 0.8:
                    to_remove.add(no_safety_vest_index)

        for index in sorted(to_remove, reverse=True):
            datas.pop(index)

        gc.collect()
        return datas

    def overlap_percentage(self, bbox1, bbox2):
        """
        Calculates the percentage of overlap between two bounding boxes.

        Args:
            bbox1 (list): The first bounding box [x1, y1, x2, y2].
            bbox2 (list): The second bounding box [x1, y1, x2, y2].

        Returns:
            float: The percentage of overlap between the two bounding boxes.
        """
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        intersection_area = max(0, x2 - x1 + 1) * max(0, y2 - y1 + 1)
        bbox1_area = (bbox1[2] - bbox1[0] + 1) * (bbox1[3] - bbox1[1] + 1)
        bbox2_area = (bbox2[2] - bbox2[0] + 1) * (bbox2[3] - bbox2[1] + 1)

        overlap_percentage = intersection_area / float(
            bbox1_area + bbox2_area - intersection_area,
        )
        gc.collect()

        return overlap_percentage

    def is_contained(self, inner_bbox, outer_bbox):
        """
        Determines if one bounding box is completely contained within another.

        Args:
            inner_bbox (list): The inner bounding box [x1, y1, x2, y2].
            outer_bbox (list): The outer bounding box [x1, y1, x2, y2].

        Returns:
            bool: Checks if inner box is fully within outer bounding box.
        """
        return (
            inner_bbox[0] >= outer_bbox[0]
            and inner_bbox[2] <= outer_bbox[2]
            and inner_bbox[1] >= outer_bbox[1]
            and inner_bbox[3] <= outer_bbox[3]
        )

    def remove_completely_contained_labels(self, datas):
        """
        Removes labels fully contained in Hardhat/Safety Vest categories.

        Args:
            datas (list): A list of detection data in YOLO format.

        Returns:
            list: Detection data with fully contained labels removed.
        """
        hardhat_indices = [
            i
            for i, d in enumerate(
                datas,
            )
            if d[5] == 0
        ]  # Indices of Hardhat detections

        # Indices of NO-Hardhat detections
        no_hardhat_indices = [i for i, d in enumerate(datas) if d[5] == 2]

        # Indices of Safety Vest detections
        safety_vest_indices = [i for i, d in enumerate(datas) if d[5] == 7]

        # Indices of NO-Safety Vest detections
        no_safety_vest_indices = [i for i, d in enumerate(datas) if d[5] == 4]

        to_remove = set()
        # Check hardhats
        for hardhat_index in hardhat_indices:
            for no_hardhat_index in no_hardhat_indices:
                if self.is_contained(
                    datas[no_hardhat_index][:4],
                    datas[hardhat_index][:4],
                ):
                    to_remove.add(no_hardhat_index)
                elif self.is_contained(
                    datas[hardhat_index][:4],
                    datas[no_hardhat_index][:4],
                ):
                    to_remove.add(hardhat_index)

        # Check safety vests
        for safety_vest_index in safety_vest_indices:
            for no_safety_vest_index in no_safety_vest_indices:
                if self.is_contained(
                    datas[no_safety_vest_index][:4],
                    datas[safety_vest_index][:4],
                ):
                    to_remove.add(no_safety_vest_index)
                elif self.is_contained(
                    datas[safety_vest_index][:4],
                    datas[no_safety_vest_index][:4],
                ):
                    to_remove.add(safety_vest_index)

        for index in sorted(to_remove, reverse=True):
            datas.pop(index)

        return datas

    async def generate_detections(
        self, frame: np.ndarray,
    ) -> tuple[list[list[float]], np.ndarray]:
        """
        Generates detections with local model or cloud API as configured.

        Args:
            frame (np.ndarray): The frame to send for detection.

        Returns:
            Tuple[List[List[float]], np.ndarray]:
                Detections and original frame.
        """
        if self.detect_with_server:
            datas = await self.generate_detections_cloud(frame)
        else:
            datas = await self.generate_detections_local(frame)
        return datas, frame

    async def run_detection(self, stream_url: str) -> None:
        """
        Runs detection on the live stream.

        Args:
            stream_url (str): The URL of the live stream.
        """
        cap = cv2.VideoCapture(stream_url)
        if not cap.isOpened():
            raise ValueError('Failed to open stream.')

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    print('Failed to read frame from the stream. Retrying...')
                    continue

                # Perform detection
                datas, frame = await self.generate_detections(frame)
                print(datas)  # You can replace this with actual processing

                cv2.imshow('Frame', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()


async def main():
    parser = argparse.ArgumentParser(
        description='Perform live stream detection and tracking using YOLO.',
    )
    parser.add_argument(
        '--url',
        type=str,
        help='Live stream URL',
        required=True,
    )
    parser.add_argument(
        '--api_url',
        type=str,
        default='http://localhost:5000',
        help='API URL for detection',
    )
    parser.add_argument(
        '--model_key',
        type=str,
        default='yolo11n',
        help='Model key for detection',
    )
    parser.add_argument(
        '--output_folder',
        type=str,
        help='Output folder for detected frames',
    )
    parser.add_argument(
        '--detect_with_server',
        action='store_true',
        help='Run detection using server api',
    )
    args = parser.parse_args()

    detector = LiveStreamDetector(
        api_url=args.api_url,
        model_key=args.model_key,
        output_folder=args.output_folder,
        detect_with_server=args.detect_with_server,
    )
    await detector.run_detection(args.url)


if __name__ == '__main__':
    anyio.run(main)
