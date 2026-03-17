from medusa.orchestrator.desktop.config import BROWSER_NAMES, PROCESS_PER_MONITOR_DPI_AWARE
from medusa.orchestrator.desktop.state import DesktopState, App, Status, Size
from medusa.orchestrator.tree.state import BoundingBox
from medusa.orchestrator.tree.inspector import Tree
from locale import getpreferredencoding
from contextlib import contextmanager
from typing import Optional,Literal
from markdownify import markdownify
from rapidfuzz import process, utils
from psutil import Process
from time import sleep
from PIL import Image
import medusa.uia as uia
import pyautogui as pg
import win32process
import subprocess
import win32gui
import win32con
import requests
import logging
import base64
import ctypes
import csv
import re
import os
import io

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('[%(levelname)s] %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

try:  
    ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
except Exception:  
    ctypes.windll.user32.SetProcessDPIAware()  


pg.FAILSAFE=False
pg.PAUSE=0.0

class Desktop:
    RENDER_W = 1024
    RENDER_H = 576

    def __init__(self):
        self.encoding=getpreferredencoding()
        self.tree=Tree(self)
        self.desktop_state=None

    def validate_loc(self, loc) -> str | None:
        if not (isinstance(loc, (list, tuple)) and len(loc) == 2):
            return "loc must be [x, y]"
        x, y = loc
        if not (isinstance(x, int) and isinstance(y, int)):
            return f"loc values must be integers, got {loc}"
        if x < 0 or y < 0:
            return f"loc values must be non-negative, got {loc}"
        if x > self.RENDER_W or y > self.RENDER_H:
            return f"loc {loc} out of render bounds ({self.RENDER_W}x{self.RENDER_H})"
        return None

    def upscale_loc(self, loc) -> tuple[int, int]:
        screen = self.get_screen_size()
        x, y = loc
        return (round(x * screen.width / self.RENDER_W), round(y * screen.height / self.RENDER_H))
        
    def get_state(self,use_vision:bool=False)->DesktopState:
        sleep(0.1)

        # Enumerate root children ONCE — shared by get_apps and tree.get_state
        root = uia.GetRootControl()
        root_children = root.GetChildren()

        apps=self._get_apps_from_children(root_children)

        active_app=self.get_active_app(apps)
        if active_app is not None and (active_app in apps):
            apps.remove(active_app)

        logger.debug(f"Active app: {active_app}")
        logger.debug(f"Apps: {apps}")
        app_handles = {a.handle for a in apps}
        if active_app is not None:
            app_handles.add(active_app.handle)
        tree_state=self.tree.get_state(active_app, root_children=root_children, app_handles=app_handles)

        if use_vision:
            screenshot=self.tree.annotated_screenshot(tree_state.interactive_nodes)
        else:
            screenshot=None

        self.desktop_state=DesktopState(apps= apps,active_app=active_app,screenshot=screenshot,tree_state=tree_state)
        return self.desktop_state
    
    def get_window_element_from_element(self,element:uia.Control)->uia.Control|None:
        '''Give any element of the app and it will return the top level window element.'''
        while element is not None:
            # Check if handle is top-level AND the element is structurally a Window or Pane
            if uia.IsTopLevelWindow(element.NativeWindowHandle):
                if element.ControlTypeName in ['WindowControl', 'PaneControl']:
                    return element
            element = element.GetParentControl()
        return None
    
    def get_active_app(self,apps:list[App]=None)->App|None:
        try:
            handle=uia.GetForegroundWindow()
            for app in (apps if apps is not None else self.get_apps()):
                if app.handle!=handle:
                    continue
                return app
        except Exception as ex:
            logger.error(f"Error in get_active_app: {ex}")
        return None
    
    def get_app_status(self,control:uia.Control)->Status:
        if uia.IsIconic(control.NativeWindowHandle):
            return Status.MINIMIZED
        elif uia.IsZoomed(control.NativeWindowHandle):
            return Status.MAXIMIZED
        elif uia.IsWindowVisible(control.NativeWindowHandle):
            return Status.NORMAL
        else:
            return Status.HIDDEN
    
    def get_cursor_location(self)->tuple[int,int]:
        position=pg.position()
        return (position.x,position.y)
    
    def get_element_under_cursor(self)->uia.Control:
        return uia.ControlFromCursor()
    
    def get_apps_from_start_menu(self)->dict[str,str]:
        command='Get-StartApps | ConvertTo-Csv -NoTypeInformation'
        apps_info,_=self.execute_command(command)
        reader=csv.DictReader(io.StringIO(apps_info))
        return {row.get('Name').lower():row.get('AppID') for row in reader}
    
    def execute_command(self,command:str)->tuple[str,int]:
        try:
            encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
            result = subprocess.run(
                ['powershell', '-NoProfile', '-EncodedCommand', encoded], 
                capture_output=True, 
                text=True,
                errors='ignore',
                timeout=25,
                cwd=os.path.expanduser(path='~')
            )
            stdout=result.stdout
            stderr=result.stderr
            return (stdout or stderr,result.returncode)
        except subprocess.TimeoutExpired:
            return ('Command execution timed out, Failed!', 1)
        except Exception as e:
            return ('Command execution failed', 1)
        
    def is_app_browser(self,node:uia.Control):
        '''Give any node of the app and it will return True if the app is a browser, False otherwise.'''
        process=Process(node.ProcessId)
        return process.name() in BROWSER_NAMES
    
    def get_default_language(self)->str:
        command="Get-Culture | Select-Object Name,DisplayName | ConvertTo-Csv -NoTypeInformation"
        response,_=self.execute_command(command)
        reader=csv.DictReader(io.StringIO(response))
        return "".join([row.get('DisplayName') for row in reader])
    
    def resize_app(self,size:tuple[int,int]=None,loc:tuple[int,int]=None)->tuple[str,int]:
        active_app=self.desktop_state.active_app
        if active_app is None:
            return "No active app found",1
        if active_app.status==Status.MINIMIZED:
            return f"{active_app.name} is minimized",1
        elif active_app.status==Status.MAXIMIZED:
            return f"{active_app.name} is maximized",1
        else:
            app_control=uia.ControlFromHandle(active_app.handle)
            if loc is None:
                x=app_control.BoundingRectangle.left
                y=app_control.BoundingRectangle.top
                loc=(x,y)
            if size is None:
                width=app_control.BoundingRectangle.width()
                height=app_control.BoundingRectangle.height()
                size=(width,height)
            x,y=loc
            width,height=size
            app_control.MoveWindow(x,y,width,height)
            return (f'{active_app.name} resized to {width}x{height} at {x},{y}.',0)
    
    def is_app_running(self,name:str)->bool:
        apps={app.name:app for app in self.get_apps()}
        return process.extractOne(name,list(apps.keys()),score_cutoff=60,processor=utils.default_process) is not None
    
    def app(self,mode:Literal['launch','switch','resize'],name:Optional[str]=None,loc:Optional[tuple[int,int]]=None,size:Optional[tuple[int,int]]=None):
        match mode:
            case 'launch':
                response,status=self.launch_app(name)
                sleep(1.25)
                if status!=0:
                    return response
                consecutive_waits=3
                for _ in range(consecutive_waits):
                    if not self.is_app_running(name):
                        sleep(1.25)
                    else:
                        return f'{name.title()} launched.'
                return f'Launching {name.title()} wait for it to come load.'
            case 'resize':
                response,status=self.resize_app(size=size,loc=loc)
                if status!=0:
                    return response
                else:
                    return response
            case 'switch':
                response,status=self.switch_app(name)
                if status!=0:
                    return response
                else:
                    return response
        
    def launch_app(self,name:str)->tuple[str,int]:
        apps_map=self.get_apps_from_start_menu()
        matched_app=process.extractOne(name,apps_map.keys(),score_cutoff=70,processor=utils.default_process)
        if matched_app is None:
            return (f'{name.title()} not found in start menu.',1)
        app_name,*_=matched_app
        appid=apps_map.get(app_name)
        if appid is None:
            return (name,f'{name.title()} not found in start menu.',1)
        if name.endswith('.exe'):
            response,status=self.execute_command(f'Start-Process {appid}')
        else:
            response,status=self.execute_command(f'Start-Process shell:AppsFolder\\{appid}')
        return response,status
    
    def switch_app(self,name:str):
        apps={app.name:app for app in [self.desktop_state.active_app]+self.desktop_state.apps if app is not None}
        matched_app:Optional[tuple[str,float,int]]=process.extractOne(name,list(apps.keys()),score_cutoff=70,processor=utils.default_process)
        if matched_app is None:
            return (f'Application {name.title()} not found.',1)
        app_name,*_=matched_app
        app=apps.get(app_name)
        target_handle=app.handle

        if uia.IsIconic(target_handle):
            uia.ShowWindow(target_handle, win32con.SW_RESTORE)
            content=f'{app_name.title()} restored from Minimized state.'
        else:
            self.bring_window_to_top(target_handle)
            content=f'Switched to {app_name.title()} window.'
        return content,0
    
    def bring_window_to_top(self,target_handle:int):
        foreground_handle=win32gui.GetForegroundWindow()
        if foreground_handle==target_handle:
            return
        foreground_thread,_=win32process.GetWindowThreadProcessId(foreground_handle)
        target_thread,_=win32process.GetWindowThreadProcessId(target_handle)
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
            win32process.AttachThreadInput(foreground_thread,target_thread,True)
            win32gui.SetForegroundWindow(target_handle)
            win32gui.BringWindowToTop(target_handle)
        except Exception as e:
            logger.error(f'Failed to bring window to top: {e}')
        finally:
            win32process.AttachThreadInput(foreground_thread,target_thread,False)
    
    def get_element_handle_from_label(self,label:int)->uia.Control:
        tree_state=self.desktop_state.tree_state
        element_node=tree_state.interactive_nodes[label]
        xpath=element_node.xpath
        element_handle=self.get_element_from_xpath(xpath)
        return element_handle
    
    def get_coordinates_from_label(self,label:int)->tuple[int,int]:
        element_handle=self.get_element_handle_from_label(label)
        bounding_rectangle=element_handle.BoundingRectangle
        return bounding_rectangle.xcenter(),bounding_rectangle.ycenter()
        
    def click(self,loc:tuple[int,int],button:str='left',clicks:int=1,modifier:str=None):
        err=self.validate_loc(loc)
        if err: return err
        x,y=self.upscale_loc(loc)
        if modifier:
            pg.keyDown(modifier)
        pg.click(x,y,button=button,clicks=clicks)
        if modifier:
            pg.keyUp(modifier)
        sleep(0.8)

    def type(self,text:str,caret_position:Literal['start','end','idle']='idle',clear:Literal['true','false']='false',press_enter:Literal['true','false']='false'):
        # loc/leftClick removed — agent clicks the target element before calling type
        if caret_position == 'start':
            pg.press('home')
        elif caret_position == 'end':
            pg.press('end')
        if clear=='true':
            pg.hotkey('ctrl','a')
            pg.press('backspace')
        pg.typewrite(text,interval=0.01)
        if press_enter=='true':
            pg.press('enter')

    def scroll(self,loc:tuple[int,int]=None,scroll_direction:Literal['up','down','left','right']='down',wheel_times:int=1,modifier:str=None)->str|None:
        if loc:
            err=self.validate_loc(loc)
            if err: return err
            self.move(loc)
        if modifier:
            pg.keyDown(modifier)
        try:
            match scroll_direction:
                case 'up':
                    uia.WheelUp(wheel_times)
                case 'down':
                    uia.WheelDown(wheel_times)
                case 'left':
                    pg.keyDown('Shift')
                    pg.sleep(0.02)
                    uia.WheelUp(wheel_times)
                    pg.sleep(0.02)
                    pg.keyUp('Shift')
                case 'right':
                    pg.keyDown('Shift')
                    pg.sleep(0.02)
                    uia.WheelDown(wheel_times)
                    pg.sleep(0.02)
                    pg.keyUp('Shift')
                case _:
                    raise ValueError(f'Invalid scroll direction "{scroll_direction}". Use "up", "down", "left", or "right".')
        finally:
            if modifier:
                pg.keyUp(modifier)
        return None
    
    def drag(self,loc:tuple[int,int],modifier:str=None):
        err=self.validate_loc(loc)
        if err: return err
        x,y=self.upscale_loc(loc)
        if modifier:
            pg.keyDown(modifier)
        pg.dragTo(x,y,duration=0.02)
        if modifier:
            pg.keyUp(modifier)

    def move(self,loc:tuple[int,int]):
        err=self.validate_loc(loc)
        if err: return err
        x,y=self.upscale_loc(loc)
        pg.moveTo(x,y,duration=0.01)

    def shortcut(self,shortcut:str):
        shortcut=shortcut.split('+')
        if len(shortcut)>1:
            pg.hotkey(*shortcut)
        else:
            pg.press(''.join(shortcut))

    def hold_key(self,key:str,duration:float):
        pg.keyDown(key)
        sleep(duration)
        pg.keyUp(key)

    def multi_select(self,press_ctrl:Literal['true','false']='false',elements:list[tuple[int,int]|int]=[]):
        if press_ctrl=='true':
            pg.keyDown('ctrl')
        for element in elements:
            x,y=element
            err=self.validate_loc((x,y))
            if err:
                pg.keyUp('ctrl')
                return err
            self.click((x,y),button='left',clicks=1)
            pg.sleep(0.0)
        pg.keyUp('ctrl')
    
    def multi_edit(self,elements:list[tuple[int,int,str]|tuple[int,str]]):
        for element in elements:
            x,y,text=element
            self.click((x,y),button='left',clicks=1)
            self.type(text=text,clear='true')
    
    def scrape(self,url:str)->str:
        response=requests.get(url,timeout=10)
        html=response.text
        content=markdownify(html=html)
        return content
    
    def get_app_from_element(self,element:uia.Control)->App|None:
        if element is None:
            return None
        top_window=element.GetTopLevelControl()
        if top_window is None:
            return None
        handle=top_window.NativeWindowHandle
        for app in self.get_apps():
            if app.handle==handle:
                return app
        return None
    
    def is_app_visible(self,app)->bool:
        is_minimized=self.get_app_status(app)!=Status.MINIMIZED
        size=app.bounding_box
        area=size.width*size.height
        is_overlay=self.is_overlay_app(app)
        return not is_overlay and is_minimized and area>10
    
    def is_overlay_app(self,element:uia.Control) -> bool:
        no_children = element.GetFirstChildControl() is None
        is_name = "Overlay" in element.Name.strip()
        return no_children or is_name
        
    def _get_apps_from_children(self, children: list) -> list[App]:
        """Build App list from pre-enumerated root children."""
        apps = []
        try:
            for depth, child in enumerate(children):
                if isinstance(child,(uia.WindowControl,uia.PaneControl)):
                    window_pattern=child.GetPattern(uia.PatternId.WindowPattern)
                    if (window_pattern is None):
                        continue
                    if window_pattern.CanMinimize and window_pattern.CanMaximize:
                        bounding_rect=child.BoundingRectangle
                        is_minimized=uia.IsIconic(child.NativeWindowHandle)
                        if bounding_rect.isempty() and not is_minimized:
                            continue
                        status = Status.MINIMIZED if is_minimized else self.get_app_status(child)
                        bounding_box=BoundingBox(
                            left=0 if is_minimized else bounding_rect.left,
                            top=0 if is_minimized else bounding_rect.top,
                            right=0 if is_minimized else bounding_rect.right,
                            bottom=0 if is_minimized else bounding_rect.bottom,
                            width=0 if is_minimized else bounding_rect.width(),
                            height=0 if is_minimized else bounding_rect.height()
                        )
                        apps.append(App(**{
                            "name":child.Name,
                            "runtime_id":tuple(child.GetRuntimeId()),
                            "depth":depth,
                            "status":status,
                            "bounding_box":bounding_box,
                            "handle":child.NativeWindowHandle,
                            "process_id":child.ProcessId,
                            "is_browser":self.is_app_browser(child)
                        }))
        except Exception as ex:
            logger.error(f"Error in _get_apps_from_children: {ex}")
        return apps

    def get_apps(self) -> list[App]:
        """Public method — enumerates root children itself."""
        desktop = uia.GetRootControl()
        children = desktop.GetChildren()
        return self._get_apps_from_children(children)
    
    def get_xpath_from_element(self,element:uia.Control):
        current=element
        if current is None:
            return ""
        path_parts=[]
        while current is not None:
            parent=current.GetParentControl()
            if parent is None:
                # we are at the root node
                path_parts.append(f'{current.ControlTypeName}')
                break
            children=parent.GetChildren()
            same_type_children=["-".join(map(lambda x:str(x),child.GetRuntimeId())) for child in children if child.ControlType==current.ControlType]
            index=same_type_children.index("-".join(map(lambda x:str(x),current.GetRuntimeId())))
            if same_type_children:
                path_parts.append(f'{current.ControlTypeName}[{index+1}]')
            else:
                path_parts.append(f'{current.ControlTypeName}')
            current=parent
        path_parts.reverse()
        xpath="/".join(path_parts)
        return xpath

    def get_element_from_xpath(self,xpath:str)->uia.Control:
        pattern = re.compile(r'(\w+)(?:\[(\d+)\])?')
        parts=xpath.split("/")
        root=uia.GetRootControl()
        element=root
        for part in parts[1:]:
            match=pattern.fullmatch(part)
            if match is None:
                continue
            control_type, index=match.groups()
            index=int(index) if index else None
            children=element.GetChildren()
            same_type_children=list(filter(lambda x:x.ControlTypeName==control_type,children))
            if index:
                element=same_type_children[index-1]
            else:
                element=same_type_children[0]
        return element
    
    def get_windows_version(self)->str:
        response,status=self.execute_command("(Get-CimInstance Win32_OperatingSystem).Caption")
        if status==0:
            return response.strip()
        return "Windows"
    
    def get_user_account_type(self)->str:
        response,status=self.execute_command("(Get-LocalUser -Name $env:USERNAME).PrincipalSource")
        return "Local Account" if response.strip()=='Local' else "Microsoft Account" if status==0 else "Local Account"
    
    def get_dpi_scaling(self):
        user32 = ctypes.windll.user32
        dpi = user32.GetDpiForSystem()
        return dpi / 96.0
    
    def get_screen_size(self)->Size:
        width, height = uia.GetScreenSize()
        return Size(width=width,height=height)

    def get_screenshot(self)->Image.Image:
        return pg.screenshot()

    def scale_image(self)->Image.Image:
        return self.get_screenshot().resize((self.RENDER_W, self.RENDER_H), Image.LANCZOS)
    
    @contextmanager
    def auto_minimize(self):
        try:
            handle = uia.GetForegroundWindow()
            uia.ShowWindow(handle, win32con.SW_MINIMIZE)
            yield
        finally:
            uia.ShowWindow(handle, win32con.SW_RESTORE)