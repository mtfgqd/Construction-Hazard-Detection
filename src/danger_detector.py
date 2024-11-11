from __future__ import annotations

import numpy as np
from shapely.geometry import MultiPoint
from shapely.geometry import Point
from shapely.geometry import Polygon
from sklearn.cluster import HDBSCAN


class DangerDetector:
    """
    A class to detect potential safety hazards based on the detection data.
    """

    def __init__(self, detection_items: dict[str, bool] = {}):
        """
        Initialises the danger detector.

        Args:
            detection_items (Dict[str, bool]): A dictionary of detection items
                to enable/disable specific safety checks. The keys are:
                - 'detect_no_safety_vest_or_helmet': Detect if workers are not
                  wearing hardhats or safety vests.
                - 'detect_near_machinery_or_vehicle': Detect if workers are
                  dangerously close to machinery or vehicles.
                - 'detect_in_restricted_area': Detect if workers are entering
                  restricted areas.

        Raises:
            ValueError: If the detection_items is not a dictionary or if any
                of the keys are not strings or values are not booleans.

        Examples:
            >>> detector = DangerDetector({
            ...     'detect_no_safety_vest_or_helmet': True,
            ...     'detect_near_machinery_or_vehicle': True,
            ...     'detect_in_restricted_area': True,
            ... })
        """
        # Initialise the HDBSCAN clusterer
        self.clusterer = HDBSCAN(min_samples=3, min_cluster_size=2)

        # Define required keys
        required_keys = {
            'detect_no_safety_vest_or_helmet',
            'detect_near_machinery_or_vehicle',
            'detect_in_restricted_area',
        }

        # Validate detection_items type and content
        if isinstance(detection_items, dict) and all(
            isinstance(k, str) and isinstance(v, bool)
            for k, v in detection_items.items()
        ) and required_keys.issubset(detection_items.keys()):
            self.detection_items = detection_items
        else:
            self.detection_items = {}

    def normalise_bbox(self, bbox):
        """
        Normalises the bounding box coordinates.

        Args:
            bbox (list[float]): The bounding box coordinates.

        Returns:
            list[float]: Normalised coordinates.
        """
        left_x = min(bbox[0], bbox[2])
        right_x = max(bbox[0], bbox[2])
        top_y = min(bbox[1], bbox[3])
        bottom_y = max(bbox[1], bbox[3])
        if len(bbox) > 4:
            return [left_x, top_y, right_x, bottom_y, bbox[4], bbox[5]]
        return [left_x, top_y, right_x, bottom_y]

    def normalise_data(self, datas):
        """
        Normalises a list of bounding box data.

        Args:
            datas (list[list[float]]): List of bounding box data.

        Returns:
            list[list[float]]: Normalised data.
        """
        return [self.normalise_bbox(data[:4] + data[4:]) for data in datas]

    def detect_polygon_from_cones(
        self,
        datas: list[list[float]],
    ) -> list[Polygon]:
        """
        Detects polygons from the safety cones in the detection data.

        Args:
            datas (List[List[float]]): The detection data.

        Returns:
            List[Polygon]: A list of polygons formed by the safety cones.
        """
        if not datas:
            return []

        # Get positions of safety cones
        cone_positions = np.array([
            (
                (float(data[0]) + float(data[2])) / 2,
                (float(data[1]) + float(data[3])) / 2,
            )
            for data in datas if data[5] == 6
        ])

        # Check if there are at least three safety cones to form a polygon
        if len(cone_positions) < 3:
            return []

        # Cluster the safety cones
        labels = self.clusterer.fit_predict(cone_positions)

        # Extract clusters
        clusters: dict[int, list[np.ndarray]] = {}
        for point, label in zip(cone_positions, labels):
            if label == -1:
                continue  # Skip noise points
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(point)

        # Create polygons from clusters
        polygons = []
        for cluster_points in clusters.values():
            if len(cluster_points) >= 3:
                polygon = MultiPoint(cluster_points).convex_hull
                polygons.append(polygon)

        return polygons

    def calculate_people_in_controlled_area(
        self,
        polygons: list[Polygon],
        datas: list[list[float]],
    ) -> int:
        """
        Calculates the number of people within the safety cone area.

        Args:
            polygons (List[Polygon]): Polygons representing controlled areas.
            datas (List[List[float]]): The detection data.

        Returns:
            int: The number of people within the controlled area.
        """
        # Check if there are any detections
        if not datas:
            return 0

        # Check if there are valid polygons
        if not polygons:
            return 0

        # Use a set to track unique people
        unique_people = set()

        # Count the number of people within the controlled area
        for data in datas:
            if data[5] == 5:  # Check if it's a person
                x_center = (data[0] + data[2]) / 2
                y_center = (data[1] + data[3]) / 2
                point = Point(x_center, y_center)
                for polygon in polygons:
                    if polygon.contains(point):
                        # Update the set of unique people
                        unique_people.add((x_center, y_center))
                        break  # No need to check other polygons

        return len(unique_people)

    def detect_danger(
        self,
        datas: list[list[float]],
    ) -> tuple[list[str], list[Polygon]]:
        """
        Detects potential safety violations in a construction site.

        This function checks for two types of safety violations:
        1. Workers entering the controlled area.
        2. Workers not wearing hardhats or safety vests.
        3. Workers dangerously close to machinery or vehicles.

        Args:
            datas (List[List[float]]): A list of detections which includes
                bounding box coordinates, confidence score, and class label.

        Returns:
            Tuple[Set[str], List[Polygon]]: Warnings and polygons list.
        """
        warnings = set()  # Initialise the list to store warning messages

        # Normalise data
        datas = self.normalise_data(datas)

        # Check if detection is enabled or no specific detection items are set
        if (
            not self.detection_items or
            self.detection_items.get('detect_in_restricted_area', False)
        ):
            # Check if people are entering the controlled area
            polygons = self.detect_polygon_from_cones(datas)
            people_count = self.calculate_people_in_controlled_area(
                polygons, datas,
            )
            if people_count > 0:
                warnings.add(
                    f"Warning: {people_count} people "
                    'have entered the controlled area!',
                )

        # Classify detected objects into different categories
        persons = [d for d in datas if d[5] == 5]  # Persons
        hardhat_violations = [d for d in datas if d[5] == 2]  # No hardhat
        safety_vest_violations = [
            d for d in datas if d[5] == 4
        ]  # No safety vest
        machinery_vehicles = [
            d for d in datas if d[5]
            in [8, 9]
        ]  # Machinery and vehicles

        # Filter out persons who are likely drivers
        if machinery_vehicles:
            non_drivers = [
                p for p in persons if not any(
                    self.is_driver(p[:4], mv[:4]) for mv in machinery_vehicles
                )
            ]
            persons = non_drivers

        # Check if detection is enabled or no specific detection items are set
        if (
            not self.detection_items or
                self.detection_items.get(
                    'detect_no_safety_vest_or_helmet', False,
                )
        ):
            # Check for hardhat and safety vest violations
            for violation in hardhat_violations + safety_vest_violations:
                label = 'NO-Hardhat' if violation[5] == 2 else 'NO-Safety Vest'
                if not any(
                    self.overlap_percentage(violation[:4], p[:4]) > 0.5
                    for p in persons
                ):
                    warning_msg = (
                        'Warning: Someone is not wearing a hardhat!'
                        if label == 'NO-Hardhat'
                        else 'Warning: Someone is not wearing a safety vest!'
                    )
                    warnings.add(warning_msg)

        # Check if detection is enabled or no specific detection items are set
        if (
            not self.detection_items or
            self.detection_items.get('detect_near_machinery_or_vehicle', False)
        ):
            # Check if anyone is dangerously close to machinery or vehicles
            for person in persons:
                for mv in machinery_vehicles:
                    label = 'machinery' if mv[5] == 8 else 'vehicle'
                    if self.is_dangerously_close(person[:4], mv[:4], label):
                        warning_msg = (
                            f"Warning: Someone is too close to {label}!"
                        )
                        warnings.add(warning_msg)
                        break

        return list(warnings), polygons

    @staticmethod
    def is_driver(person_bbox: list[float], vehicle_bbox: list[float]) -> bool:
        """
        Check if a person is a driver based on position near a vehicle.

        Args:
            person_bbox (list[float]): Bounding box of person.
            vehicle_bbox (list[float]): Bounding box of vehicle.

        Returns:
            bool: True if the person is likely the driver, False otherwise.
        """
        # Extract coordinates and dimensions of person and vehicle boxes
        person_bottom_y = person_bbox[3]
        person_top_y = person_bbox[1]
        person_left_x = person_bbox[0]
        person_right_x = person_bbox[2]
        person_width = person_bbox[2] - person_bbox[0]
        person_height = person_bbox[3] - person_bbox[1]

        vehicle_top_y = vehicle_bbox[1]
        vehicle_bottom_y = vehicle_bbox[3]
        vehicle_left_x = vehicle_bbox[0]
        vehicle_right_x = vehicle_bbox[2]
        vehicle_height = vehicle_bbox[3] - vehicle_bbox[1]

        # 1. Check vertical bottom position: person's bottom should be above
        #    the vehicle's bottom by at least half the person's height
        if not (
            person_bottom_y < vehicle_bottom_y
            and vehicle_bottom_y - person_bottom_y >= person_height / 2
        ):
            return False

        # 2. Check horizontal position: person's edges should not extend
        #    beyond half the width of the person from the vehicle's edges
        if not (
            person_left_x >= vehicle_left_x - person_width / 2
            and person_right_x <= vehicle_right_x + person_width / 2
        ):
            return False

        # 3. The person's top must be below the vehicle's top
        if not (person_top_y > vehicle_top_y):
            return False

        # 4. Person's height is less than or equal to half the vehicle's height
        if not (person_height <= vehicle_height / 2):
            return False

        return True

    @staticmethod
    def overlap_percentage(
        bbox1: list[float],
        bbox2: list[float],
    ) -> float:
        """
        Calculate the overlap percentage between two bounding boxes.

        Args:
            bbox1 (list[float]): The first bounding box.
            bbox2 (list[float]): The second bounding box.

        Returns:
            float: The overlap percentage.
        """
        # Calculate the coordinates of the intersection rectangle
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        # Calculate the area of the intersection rectangle
        overlap_area = max(0, x2 - x1) * max(0, y2 - y1)

        # Calculate the area of both bounding boxes
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])

        # Calculate the overlap percentage
        return overlap_area / float(area1 + area2 - overlap_area)

    @staticmethod
    def is_dangerously_close(
        person_bbox: list[float],
        vehicle_bbox: list[float],
        label: str,
    ) -> bool:
        """
        Determine if a person is dangerously close to machinery or vehicles.

        Args:
            person_bbox (list[float]): Bounding box of person.
            vehicle_bbox (list[float]): Machine/vehicle box.
            label (str): Type of the second object ('machinery' or 'vehicle').

        Returns:
            bool: True if the person is dangerously close, False otherwise.
        """
        # Calculate dimensions of the person bounding box
        person_width = person_bbox[2] - person_bbox[0]
        person_height = person_bbox[3] - person_bbox[1]
        person_area = person_width * person_height

        # Calculate the area of the vehicle bounding box
        vehicle_area = (vehicle_bbox[2] - vehicle_bbox[0]) * \
            (vehicle_bbox[3] - vehicle_bbox[1])
        acceptable_ratio = 0.1 if label == 'vehicle' else 0.05

        # Check if person area ratio is acceptable compared to vehicle area
        if person_area / vehicle_area > acceptable_ratio:
            return False

        # Define danger distances
        danger_distance_horizontal = 5 * person_width
        danger_distance_vertical = 1.5 * person_height

        # Calculate min horizontal/vertical distance between person and vehicle
        horizontal_distance = min(
            abs(person_bbox[2] - vehicle_bbox[0]),
            abs(person_bbox[0] - vehicle_bbox[2]),
        )
        vertical_distance = min(
            abs(person_bbox[3] - vehicle_bbox[1]),
            abs(person_bbox[1] - vehicle_bbox[3]),
        )

        # Determine if the person is dangerously close
        return (
            horizontal_distance <= danger_distance_horizontal
            and vertical_distance <= danger_distance_vertical
        )


def main():
    detector = DangerDetector()

    data: list[list[float]] = [
        [50, 50, 150, 150, 0.95, 0],    # Hardhat
        [200, 200, 300, 300, 0.85, 5],  # Person
        [400, 400, 500, 500, 0.75, 2],  # NO-Hardhat
        [0, 0, 10, 10, 0.88, 6],  # Safety cone
        [0, 1000, 10, 1010, 0.87, 6],  # Safety cone
        [1000, 0, 1010, 10, 0.89, 6],  # Safety cone
        [100, 100, 120, 120, 0.9, 6],  # Safety cone
        [150, 150, 170, 170, 0.85, 6],  # Safety cone
        [200, 200, 220, 220, 0.89, 6],  # Safety cone
        [250, 250, 270, 270, 0.85, 6],  # Safety cone
        [450, 450, 470, 470, 0.92, 6],  # Safety cone
        [500, 500, 520, 520, 0.88, 6],  # Safety cone
        [550, 550, 570, 570, 0.86, 6],  # Safety cone
        [600, 600, 620, 620, 0.84, 6],  # Safety cone
        [650, 650, 670, 670, 0.82, 6],  # Safety cone
        [700, 700, 720, 720, 0.80, 6],  # Safety cone
        [750, 750, 770, 770, 0.78, 6],  # Safety cone
        [800, 800, 820, 820, 0.76, 6],  # Safety cone
        [850, 850, 870, 870, 0.74, 6],  # Safety cone
    ]

    warnings, polygons = detector.detect_danger(data)
    print(f"Warnings: {warnings}")
    print(f"Polygons: {polygons}")


if __name__ == '__main__':
    main()
