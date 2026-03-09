import tempfile
import pyautogui
import time
import base64
from pathlib import Path
from uuid import uuid4
import subprocess
from io import BytesIO
from PIL import Image
import uiautomation as uia


class ComputerTool:
    name = "computer"


    def __init__(self):
        screen_width, screen_height = pyautogui.size()
        self.or_width = screen_width
        self.or_height = screen_height        
        self.down_w = 1024
        self.down_h = round(self.down_w * (self.or_height / self.or_width))  

    def screenshot(self):
        try:
            screenshot = pyautogui.screenshot()

            resized = screenshot.resize(
                (self.down_w, self.down_h),
                resample=Image.LANCZOS
            )

            buffer = BytesIO()
            resized.save(buffer, format="PNG")
            base64_image = base64.b64encode(buffer.getvalue()).decode()

            return self._result(output="screenshot captured", image=base64_image)

        except Exception as e:
            return self._result(error=f"error: screenshot failed: {e}")

    def upscale_coordinates(self, x_down, y_down):        
        scale_x = self.or_width / self.down_w
        scale_y = self.or_height / self.down_h
        x_real = int(x_down * scale_x)
        y_real = int(y_down * scale_y)
        return x_real, y_real
    
    def _result(self, output=None, error=None, image=None):
        return {
            "output": output,
            "error": error,
            "base64_image": image,
        }
    def validate_coordinates(self, coordinate):
        """
        Validate and upscale coordinates provided by the model.
        """  
        if coordinate is None:
            return self._result(error="coordinate is required but missing")        
        if not (
            isinstance(coordinate, list)
            and len(coordinate) == 2
            and all(isinstance(v, int) for v in coordinate)
        ):
            return self._result(
                error=f"coordinate must be a list of two integers, received: {coordinate}"
            )
        x, y = coordinate       
        if x < 0 or y < 0:
            return self._result(
                error=f"coordinate values must be non-negative, received: {coordinate}"
            )        
        if x > self.down_w or y > self.down_h:
            return self._result(
                error=(
                    f"coordinate {coordinate} exceeds tool display bounds "
                    f"({self.down_w}×{self.down_h})"
                )
            )        
        return self.upscale_coordinates(x, y)

    async def __call__(self, *, action, coordinate=None, text=None, **kwargs):
        try:
            if action == "mouse_move":
                validated = self.validate_coordinates(coordinate)
                if isinstance(validated, dict):
                    return validated

                x_real, y_real = validated
                pyautogui.moveTo(x_real, y_real)
                return self._result(output=f"mouse moved to {coordinate}")


            elif action == "left_click":
                if coordinate:
                    validated = self.validate_coordinates(coordinate)
                    if isinstance(validated, dict):
                        return validated

                    x_real, y_real = validated
                    pyautogui.moveTo(x_real, y_real)
                    pyautogui.click()
                    return self._result(output=f"mouse moved to {coordinate} and left clicked")

                pyautogui.click()
                return self._result(output="left click")


            elif action == "right_click":
                pyautogui.click(button="right")
                return self._result(output="right click")


            elif action == "double_click":
                if coordinate:
                    validated = self.validate_coordinates(coordinate)
                    if isinstance(validated, dict):
                        return validated

                    x_real, y_real = validated
                    pyautogui.moveTo(x_real, y_real)
                    pyautogui.doubleClick()
                    return self._result(output=f"mouse moved to {coordinate} and double clicked")

                pyautogui.doubleClick()
                return self._result(output="double click")

                
            elif action == "scroll":
                direction = kwargs.get("scroll_direction")
                amount = kwargs.get("scroll_amount")

                # Validate
                if direction not in ("up", "down", "left", "right"):
                    return self._result(error=f"invalid scroll_direction: {direction}")

                if not isinstance(amount, int) or amount <= 0:
                    return self._result(error="scroll_amount must be positive int")

                # Move if needed
                if coordinate:
                    x, y = self.upscale_coordinates(*coordinate)
                    pyautogui.moveTo(x, y)

                # Apply scroll
                if direction in ("up", "down"):
                    if direction == "up":
                        uia.WheelUp(amount)
                    elif direction == "down":
                        uia.WheelDown(amount)
                else:
                    pyautogui.keyDown("shift")
                    try:
                        if direction == "left":
                            uia.WheelUp(amount)
                        elif direction == "right":
                            uia.WheelDown(amount)
                    finally:
                        pyautogui.keyUp("shift")

                return self._result(output=f"scrolled {direction} by {amount}")

            elif action == "type":
                if not text:
                    return self._result(error="error: text required for type")
                else:
                    pyautogui.write(text, interval=0.05)
                    return self._result(output=f"typed: {text}")
                
            elif action == "key":
                if not text:
                    return self._result(error="error: key action requires text")
                else:
                    pyautogui.press(text)
                    return self._result(output=f"pressed key: {text}")

            elif action == "cursor_position":
                x, y = pyautogui.position()                
                down_x = int(x * (self.down_w / self.or_width))
                down_y = int(y * (self.down_h / self.or_height))
                return self._result(output=[down_x, down_y])

            elif action == "wait":
                requested_duration = kwargs.get("duration")                
                if not isinstance(requested_duration, (int, float)) or requested_duration < 0:                    
                    requested_duration = 0.5
                    time.sleep(0.5)
                    return self._result(output=f"waited for {requested_duration} seconds")
               
                if requested_duration <= 3:
                    time.sleep(0.5)
                elif requested_duration == 4:
                    time.sleep(0.7)                    
                else:  
                    time.sleep(requested_duration)                    
                return self._result(output=f"waited for {requested_duration} seconds")

            elif action == "screenshot":
                return self.screenshot()

            else:
                return self._result(error=f"error: unknown action {action}")

        except Exception as e:
            return self._result(error=f"error: {e}")

        

   




# import io, base64
# import pyautogui

# screenshot = pyautogui.screenshot()
# buffer = io.BytesIO()
# screenshot.save(buffer, format="PNG")
# img_base64 = base64.b64encode(buffer.getvalue()).decode()

# return {
#     "output": "screenshot taken",
#     "error": None,
#     "base64_image": img_base64,
# }


# elif action == "screenshot":
#                 tmp_path = Path(tempfile.gettempdir()) / f"screenshot_{uuid4().hex}.png"
#                 screenshot = pyautogui.screenshot()
#                 screenshot.save(tmp_path)

#                 if tmp_path.exists():

#                     # Downscale for model (1024 width)
#                     downscaled_path = Path(tempfile.gettempdir()) / f"scaled_{uuid4().hex}.png"

#                     cmd = [
#                         "magick",
#                         str(tmp_path),
#                         "-resize", f"{self.down_w}",
#                         downscaled_path
#                     ]

#                     subprocess.run(cmd, check=True)

#                     output = "screenshot captured"
#                     base64_image = base64.b64encode(downscaled_path.read_bytes()).decode()

#                 else:
#                     error = "error: failed to take screenshot"