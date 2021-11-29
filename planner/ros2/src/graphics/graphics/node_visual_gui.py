#!/usr/bin/env python3
# =============================================================================
"""
Code Information:
    Maintainer: Eng. John Alberto Betancourt G
	Mail: john@kiwicampus.com
	Kiwi Campus / Computer & Ai Vision Team
"""

# =============================================================================
import numpy as np
import cv2
import copy
import sys
import os

# =============================================================================
# Added time an datetime libraries to get tame and date
# to write them in the csv file
import time
import datetime

# =============================================================================

from threading import Thread, Event

from std_msgs.msg import Int32

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from rclpy.logging import get_logger
from rclpy.node import Node

from utils.python_utils import printlog
from utils.python_utils import print_list_text

from usr_msgs.msg import Planner as planner_msg
from usr_msgs.msg import Kiwibot as kiwibot_msg

# =============================================================================
def setProcessName(name: str) -> None:
    """!
    Function for seting the process name
    @see name 'str' defining the process name
    """
    if sys.platform in ["linux2", "linux"]:
        import ctypes

        libc = ctypes.cdll.LoadLibrary("libc.so.6")
        libc.prctl(15, name, 0, 0, 0)
    else:
        raise Exception(
            "Can not set the process name on non-linux systems: " + str(sys.platform)
        )


# =============================================================================
# function to write the csv file during execution
def write_csv(total_distance: float, total_time: float):
    """! [write a csv file with routine information]

    @param total_distance (float) [Total distance travel]
    @param total_time (float) [total travel time]
    """
    # Read the csv file
    with open(
        "/workspace/planner/configs/kiwibot_history.csv", "r", encoding="utf-8"
    ) as r:
        r = r.readlines()
        last_line = r[-1].split(",")
        msg = (
            str(datetime.date.today())
            + ","
            + datetime.datetime.now().strftime("%H:%M:%S")
            + "GTM"
            + time.strftime("%z")
            + ","
            + last_line[2]
            + ","
            + str(total_distance)
            + ","
            + str(total_time)
            + ","
            + "0"
            + "\n"
        )
        try:
            # Check if the routine has been completed to stop overwriting
            if last_line[-1][-2] != "1":
                r[-1] = msg
                with open(
                    "/workspace/planner/configs/kiwibot_history.csv",
                    "w",
                    encoding="utf-8",
                ) as w:
                    w.writelines(r)
        except Exception:
            r[-1] = msg
            with open(
                "/workspace/planner/configs/kiwibot_history.csv", "w", encoding="utf-8"
            ) as w:
                w.writelines(r)


# =============================================================================
# Function to get the total distance of the csv file
def total_distance():
    tacometer = 0.0
    with open(
        "/workspace/planner/configs/kiwibot_history.csv",
        "r",
        encoding="utf-8",
    ) as r:
        r = r.readlines()
        for lines in range(1, len(r)):
            actual_line = r[lines].split(",")
            # Accumulate all distances
            tacometer += float(actual_line[3])
    return tacometer


# =============================================================================
class VisualsNode(Thread, Node):
    def __init__(self) -> None:
        """
            Class constructor for visuals and graphics node
        Args:
        Returns:
        """
        # =============================================================================
        # Some control variables for stop, tacometer, angle, routine, and distance
        self.stop = False
        self.routine_id = 0
        self.stage_distance = 0.0
        self.tacometer_erase = 0.0
        self.tacometer_counter = True
        self.angle_acum = 90.0
        printlog(msg=f"Press ENTER to erase o resume tacometer", msg_type="OKGREEN")
        printlog(msg=f"Press SPACEBAR to stop o resume execution", msg_type="OKGREEN")
        # =============================================================================
        # ---------------------------------------------------------------------
        Thread.__init__(self)
        Node.__init__(self, node_name="visuals_node")

        # Allow callbacks to be executed in parallel without restriction.
        self.callback_group = ReentrantCallbackGroup()

        # ---------------------------------------------------------------------
        # Window properties
        self._win_name = "planner_window"
        self._win_size = (640, 480)  # maps window shape/size
        self._win_time = 100

        # Read back ground map
        self._win_background_path = "/workspace/planner/media/images/map.jpg"
        self._win_background = cv2.imread(self._win_background_path)

        self._kiwibot_img_path = "/workspace/planner/media/images/kiwibot.png"
        self._kiwibot_img = cv2.imread(self._kiwibot_img_path, cv2.IMREAD_UNCHANGED)
        # =============================================================================
        self._original_kiwibot_img = self._kiwibot_img
        # =============================================================================

        # ---------------------------------------------------------------------
        # Subscribers

        self.msg_planner = planner_msg()
        # TODO: Implement the path planner status subscriber,
        # topic name: "/path_planner/msg"
        # message type: planner_msg
        # callback:cb_path_planner
        # add here your solution

        # create a subscription based on the publisher in path planner node, using it's qos
        self.create_subscription(
            planner_msg,
            "/path_planner/msg",
            self.cb_path_planner,
            qos_profile=qos_profile_sensor_data,
        )

        # ------------------------------------------
        # TODO: Implement the Kiwibot status subscriber,

        # create a subscription based on the publisher in kiwibot node, using it's qos
        self.create_subscription(
            kiwibot_msg,
            "/kiwibot/status",
            self.cb_kiwibot_status,
            qos_profile=qos_profile_sensor_data,
        )

        # topic name: "/kiwibot/status"
        # message type: kiwibot_msg
        # callback:cb_kiwibot_status
        # add here your solution
        self.msg_kiwibot = kiwibot_msg()
        self.turn_robot(heading_angle=float(os.getenv("BOT_INITIAL_YAW", default=0.0)))
        self.msg_kiwibot.pos_x = int(os.getenv("BOT_INITIAL_X", default=917))
        self.msg_kiwibot.pos_y = int(os.getenv("BOT_INITIAL_Y", default=1047))

        # ---------------------------------------------------------------------
        # Publishers

        # Publisher for activating the routines

        self.msg_path_number = Int32()
        self.pub_start_routine = self.create_publisher(
            msg_type=Int32,
            topic="/graphics/start_routine",
            qos_profile=1,
            callback_group=self.callback_group,
        )

        # ---------------------------------------------------------------------
        self.damon = True
        self.run_event = Event()
        self.run_event.set()
        self.start()

    def cb_path_planner(self, msg: planner_msg) -> None:
        """
        Callback to update path planner state information in visuals
        Args:
            msg: `planner_msg` message with planner state information
                LandMark[] land_marks       # landmarks of planner routine
                    int8[] neighbors    # id of closer neighbors
                    int8 id             # id unic landmark identifier
                    int32 x             # x axis position
                    int32 y             # y axis position
                float32 distance            # in meters
                float32 duration            # in seconds
                float32 difficulty          # in seconds
        Returns:
        """

        try:
            self.msg_planner = msg

            # Read again background image to update visuals and components
            self._win_background = cv2.imread(self._win_background_path)
            self._kiwibot_img = cv2.imread(self._kiwibot_img_path, cv2.IMREAD_UNCHANGED)
            self.turn_robot(
                heading_angle=float(os.getenv("BOT_INITIAL_YAW", default=0.0))
            )
            self.draw_descriptors(self.msg_planner.land_marks)

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            printlog(
                msg="{}, {}, {}, {}".format(e, exc_type, fname, exc_tb.tb_lineno),
                msg_type="ERROR",
            )

    def cb_kiwibot_status(self, msg: kiwibot_msg) -> None:
        """
            Callback to update kiwibot state information in visuals
        Args:
            msg: `kiwibot_msg` message with  kiwibot state information
                int8 pos_x      # x axis position in the map
                int8 pos_y      # y axis position in the map
                float32 dist    # distance traveled by robot
                float32 speed   # speed m/s
                float32 time    # time since robot is moving
                float32 yaw     # time since robot is moving
                bool moving     # Robot is moving
        Returns:
        """

        try:
            # rotate robot's image
            if self.msg_kiwibot.yaw != msg.yaw:
                if not int((msg.yaw - int(msg.yaw)) * 100):
                    self._kiwibot_img = cv2.imread(
                        self._kiwibot_img_path, cv2.IMREAD_UNCHANGED
                    )
                    self.turn_robot(heading_angle=msg.yaw)
                else:
                    move_angle = msg.yaw - self.msg_kiwibot.yaw
                    self.turn_robot(heading_angle=move_angle)

            self.msg_kiwibot = msg

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            printlog(
                msg="{}, {}, {}, {}".format(e, exc_type, fname, exc_tb.tb_lineno),
                msg_type="ERROR",
            )

    def crop_map(self, coord: tuple, draw_path: bool = True):
        """
            Gets a valid windows or roi in map image
        Args:
            coord: `tuple` coordinate with center of window
            draw_path: `boolean` enable/disable path drawings
        Returns:
            roi_map: `cv2.math` valid windows or roi in map image
            roi_coord: `tuple` recenter input coordinate if condition is applied
        """

        # Draws window center
        if draw_path:
            cv2.circle(
                img=self._win_background,
                center=tuple(coord),
                radius=2,
                color=(0, 0, 255),
                thickness=-1,
            )

        coord = list(coord)
        win_half_width = int(self._win_size[0] * 0.5)
        win_half_height = int(self._win_size[1] * 0.5)
        roi_coord = (win_half_width, win_half_height)

        # If window is out of boundaries to the:
        CON_L = coord[0] - win_half_width < 0  # 1 - left
        CON_R = coord[0] + win_half_width > self._win_background.shape[1]  # 2 - right
        CON_T = coord[1] - win_half_height < 0  # 3 - top
        CON_B = coord[1] + win_half_height > self._win_background.shape[0]  # 4 - bottom

        if CON_L and not CON_T and not CON_B:
            roi_coord = (coord[0], win_half_height)
            coord[0] = win_half_width
        elif CON_R and not CON_T and not CON_B:
            roi_coord = (
                coord[0] - (self._win_background.shape[1] - win_half_width * 2),
                win_half_height,
            )
            coord[0] = self._win_background.shape[1] - win_half_width
        elif CON_T and not CON_L and not CON_R:
            roi_coord = (win_half_width, coord[1])
            coord[1] = win_half_height
        elif CON_B and not CON_L and not CON_R:
            roi_coord = (
                win_half_width,
                coord[1] - (self._win_background.shape[0] - win_half_height * 2),
            )
            coord[1] = self._win_background.shape[0] - win_half_height
        elif CON_L and CON_T:
            roi_coord = copy.deepcopy(coord)
            coord[1] = win_half_height
            coord[0] = win_half_width
        elif CON_R and CON_T:
            roi_coord = (
                coord[0] - (self._win_background.shape[1] - win_half_width * 2),
                coord[1],
            )
            coord[0] = self._win_background.shape[1] - win_half_width
            coord[1] = win_half_height
        elif CON_R and CON_B:
            roi_coord = (
                coord[0] - (self._win_background.shape[1] - win_half_width * 2),
                coord[1] - (self._win_background.shape[0] - win_half_height * 2),
            )
            coord[0] = self._win_background.shape[1] - win_half_width
            coord[1] = self._win_background.shape[0] - win_half_height
        elif CON_L and CON_B:
            roi_coord = (
                coord[0],
                coord[1] - (self._win_background.shape[0] - win_half_height * 2),
            )
            coord[0] = win_half_width
            coord[1] = self._win_background.shape[0] - win_half_height

        roi_map = self._win_background.copy()[
            coord[1] - win_half_height : coord[1] + win_half_height,
            coord[0] - win_half_width : coord[0] + win_half_width,
        ]

        cv2.circle(
            img=roi_map,
            center=tuple(roi_coord),
            radius=6,
            color=(0, 255, 0),
            thickness=2,
        )

        return roi_map, roi_coord

    def turn_robot(self, heading_angle: float = 0.0) -> np.ndarray:
        """
            Turns the image of the robot
        Args:
            heading_angle: `float` new robots heading angle
        Returns:
        """

        # Get image shape
        rows, cols, _ = self._kiwibot_img.shape

        # =============================================================================
        # Accumulating and correcting the angle of rotation
        if heading_angle < 20:
            self.angle_acum += heading_angle
        elif (
            heading_angle > self.angle_acum - 5 and heading_angle < self.angle_acum + 5
        ):
            self.angle_acum = heading_angle
        # =============================================================================

        # Calculate translation and rotation matrix
        # Angle changed to an absolute angle
        M = cv2.getRotationMatrix2D(
            center=(int(cols / 2), int(rows / 2)),
            angle=(self.angle_acum),
            scale=1,
        )

        # Rotate robots image
        # Rotating only the original image
        self._kiwibot_img = cv2.warpAffine(
            src=self._original_kiwibot_img,
            M=M,
            dsize=(cols, rows),
            flags=cv2.INTER_CUBIC,
        )

    # TODO: Draw the robot
    def draw_robot(
        self, l_img: np.ndarray, s_img: np.ndarray, pos: tuple, transparency=1.0
    ) -> np.ndarray:
        """
            Draws robot in maps image
        Args:
            l_img: `cv2.mat` inferior image to overlay superior image
            s_img: `cv2.mat` superior image to overlay
            pos: `tuple`  position to overlay superior image [pix, pix]
            transparency: `float` transparency in overlayed image
        Returns:
            _: Image with robot drawn
        """

        # -----------------------------------------
        # Insert you solution here

        # get the upper left corner position from where the robot will be drawn is obtained
        y = pos[1] - s_img.shape[1] // 2
        x = pos[0] - s_img.shape[1] // 2

        # Extract the alpha mask of the RGBA image, convert to RGB
        b, g, r, a = cv2.split(s_img)
        overlay_color = cv2.merge((b, g, r))

        # Apply some simple filtering to remove edge noise
        mask = cv2.medianBlur(a, 5)

        h, w, _ = overlay_color.shape
        roi = l_img[y : y + h, x : x + w]

        # Black-out the area behind the image in our original ROI
        img1_bg = cv2.bitwise_and(roi.copy(), roi.copy(), mask=cv2.bitwise_not(mask))

        # Mask out the robot image from the robot image.
        img2_fg = cv2.bitwise_and(overlay_color, overlay_color, mask=mask)

        # Update the original image with our new ROI, adding transparency
        l_img[y : y + h, x : x + w] = cv2.addWeighted(
            img1_bg, 1.0, img2_fg, transparency, 0
        )

        return l_img

        # -----------------------------------------

    def draw_map(self) -> np.ndarray:
        """
            Draws map and all components and descriptors
        Args:
        Returns:
            _: map Image with all components and descriptors drawn
        """

        # Get the initial coordinate
        coord = (self.msg_kiwibot.pos_x, self.msg_kiwibot.pos_y)

        # Get a valid window where the robot is in the map
        win_img, robot_coord = self.crop_map(coord=coord)

        # Draws robot in maps image
        if coord[0] and coord[1]:
            win_img = self.draw_robot(
                l_img=win_img, s_img=self._kiwibot_img, pos=robot_coord
            )

        # Draw descriptions
        str_list = [
            "LandMarks: {}".format(len(self.msg_planner.land_marks)),
            "Distance [m]: {}".format(round(self.msg_planner.distance, 2)),
            "Duration [s]: {}".format(round(self.msg_planner.duration, 2)),
            "Difficulty: {}/5.00".format(round(self.msg_planner.difficulty, 2)),
        ]
        win_img = print_list_text(
            win_img,
            str_list,
            origin=(10, 20),
            color=(0, 255, 255),
            line_break=18,
            thickness=1,
            fontScale=0.4,
        )

        str_list = [
            "Positions: {}, {}".format(self.msg_kiwibot.pos_x, self.msg_kiwibot.pos_y),
            "Distance Traveled [m]: {}".format(round(self.msg_kiwibot.dist, 2)),
            "Yaw [deg]: {}".format(round(self.msg_kiwibot.yaw, 2)),
            "Linear Speed [m/s]: {}".format(round(self.msg_kiwibot.speed, 2)),
            "Time [s]: {}".format(round(self.msg_kiwibot.time, 2)),
        ]
        win_img = print_list_text(
            win_img,
            str_list,
            origin=(10, 100),
            color=(255, 255, 0),
            line_break=18,
            thickness=1,
            fontScale=0.4,
        )

        # Calculate the pergentage of the total routine only if there's
        # A routine active
        if self.msg_kiwibot.dist >= self.msg_planner.distance:
            # Actualice the distance of the accumulated stages
            self.max_distance = self.msg_kiwibot.dist
        if self.stage_distance > 0:
            # Get the actual distance of the stage
            distance = self.msg_kiwibot.dist - self.stage_distance
        else:
            distance = self.msg_kiwibot.dist
        try:
            # calculate the percentage
            porc = str(
                round(
                    distance / (self.msg_planner.distance - self.stage_distance) * 100,
                    2,
                )
            )
        # If the robot has not moved the percentage is 0
        except ZeroDivisionError:
            porc = "0.00"
        # =============================================================================

        win_img = print_list_text(
            win_img,
            [f"Porc: {porc}%"],
            origin=(10, 200),
            color=(255, 0, 255),
            line_break=18,
            thickness=1,
            fontScale=0.4,
        )
        # =============================================================================
        # verify if there is any routine active to actualice the csv file
        if self.routine_id != 0:
            write_csv(
                round(distance, 2),
                round(self.msg_kiwibot.time, 2),
            )
        # =============================================================================
        # =============================================================================
        # Tacometer calculations
        if self.tacometer_counter:
            tacometer = total_distance()
        else:
            tacometer = total_distance() - self.tacometer_erase

        # Print tacometer in the screen
        win_img = print_list_text(
            win_img,
            [f"Tacometer: {round(tacometer,2)}m"],
            origin=(10, 250),
            color=(0, 0, 255),
            line_break=18,
            thickness=1,
            fontScale=0.4,
        )
        # =============================================================================

        return win_img

    # TODO: Drawing map descriptors
    def draw_descriptors(self, land_marks: list) -> None:
        """
            Draws maps keypoints in map image
        Args:
            img_src: `cv2.math` map image
        Returns:
            _: `cv2.math` map image with keypoints drawn
        """

        # -----------------------------------------
        # Insert you solution here

        # drawing every circle in the landmark using cv2.circle witch recives:
        # img: the image to which the circle is to be drawn
        # center: the coordinates of the center of the circle
        # radius: the radius of the circle
        # color: rgb color of the circle
        # thickness: the thickness of the circle
        for pos in land_marks:
            cv2.circle(
                img=self._win_background,
                center=tuple((pos.x, pos.y)),
                radius=10,
                color=(0, 0, 255),
                thickness=2,
            )

        # -----------------------------------------

    def run(self) -> None:
        """
            Callback to update & draw window components
        Args:
        Returns:
        """

        if self._win_background is None or self._kiwibot_img is None:
            return

        try:
            while True:

                win_img = self.draw_map()

                if not self.msg_kiwibot.moving:
                    print_list_text(
                        win_img,
                        ["press 1 to 9 to start a routine"],
                        origin=(
                            win_img.shape[1] - 550,
                            int(win_img.shape[0] * 0.95),
                        ),
                        color=(0, 0, 255),
                        line_break=20,
                        thickness=1,
                        fontScale=0.8,
                    )

                # Update the images dictionary in the callback action
                cv2.imshow(self._win_name, win_img)
                key = cv2.waitKey(self._win_time)

                # No key
                if key == -1:
                    continue
                # Key1=1048633 & Key9=1048625
                elif key >= 49 and key <= 57:
                    # printlog(
                    #     msg=f"Code is broken here",
                    #     msg_type="WARN",
                    # )
                    # continue

                    printlog(
                        msg=f"Routine {chr(key)} was sent to path planner node",
                        msg_type="INFO",
                    )

                    # =============================================================================
                    # Actualice control variables
                    self.routine_id = int(chr(key))
                    self.stage_distance = self.max_distance
                    # =============================================================================

                    self.pub_start_routine.publish(Int32(data=int(chr(key))))

                # =============================================================================
                #
                elif key == 32:
                    self.pub_start_routine.publish(Int32(data=0))
                    self.stop = not self.stop
                # If enter is pressed it check if the tacometer is cleared before or not
                elif key == 13:
                    # If is the first time pressed actualice self.tacometer_erase
                    if self.tacometer_counter == True:
                        self.tacometer_erase = total_distance()
                        self.tacometer_counter = not self.tacometer_counter
                        printlog(
                            msg=f"Tacometer clear",
                            msg_type="OKGREEN",
                        )
                    # If is the second time pressed enter, clean self.tacometer_erase
                    # To restore tacometer
                    else:
                        self.tacometer_erase = 0
                        self.tacometer_counter = not self.tacometer_counter
                        printlog(
                            msg=f"Tacometer resumed",
                            msg_type="OKGREEN",
                        )
                # =============================================================================
                else:

                    printlog(
                        msg=f"No action for key {chr(key)} -> {key}",
                        msg_type="WARN",
                    )

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            printlog(
                msg="{}, {}, {}, {}".format(e, exc_type, fname, exc_tb.tb_lineno),
                msg_type="ERROR",
            )


# =============================================================================
def main(args=None):
    """!
    Main Functions of Local Console Node
    """
    # Initialize ROS communications for a given context.
    setProcessName("visuals-node")
    rclpy.init(args=args)

    # Execute work and block until the context associated with the
    # executor is shutdown.
    visuals_node = VisualsNode()

    # Runs callbacks in a pool of threads.
    executor = MultiThreadedExecutor()

    # Execute work and block until the context associated with the
    # executor is shutdown. Callbacks will be executed by the provided
    # executor.
    rclpy.spin(visuals_node, executor)

    # Clear thread
    visuals_node.clear()

    # Destroy the node explicitly
    # (optional - otherwise it will be done automatically
    # when the garbage collector destroys the node object)
    visuals_node.destroy_node()
    rclpy.shutdown()


# =============================================================================
if __name__ == "__main__":
    main()

# =============================================================================
