/* Experimental no-global-input Revu test-document driver.
 * No SetCursorPos, SendInput, SetFocus, or foreground activation calls.
 */
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static HWND root, initial_foreground;
static DWORD owner;
static const char *expected_title;
static POINT initial_cursor;
static HWND pressed_window;
static POINT last_point;
static void cleanup_button(void) {
    if(pressed_window && IsWindow(pressed_window)) {
        DWORD_PTR r;
        SendMessageTimeoutA(pressed_window,WM_LBUTTONUP,0,MAKELPARAM(last_point.x,last_point.y),SMTO_ABORTIFHUNG,500,&r);
    }
}
static BOOL CALLBACK find(HWND h, LPARAM unused) {
    char title[512];GetWindowTextA(h,title,sizeof title);
    if(strstr(title,expected_title) && strstr(title,"Bluebeam Revu x64")) {
        if(root)exit(3);
        root=h;GetWindowThreadProcessId(root,&owner);
    }return TRUE;
}
static int untouched(void) {
    POINT p;GetCursorPos(&p);
    HWND current=GetForegroundWindow();
    if(current!=initial_foreground || p.x!=initial_cursor.x || p.y!=initial_cursor.y)
        fprintf(stderr,"state expected_fg=%p current_fg=%p expected_cursor=%ld,%ld current_cursor=%ld,%ld\n",initial_foreground,current,initial_cursor.x,initial_cursor.y,p.x,p.y);
    return current==initial_foreground && p.x==initial_cursor.x && p.y==initial_cursor.y;
}
static HWND resolve(POINT *p) {
    HWND h=root;
    for(int i=0;i<32;i++) {
        HWND next=ChildWindowFromPointEx(h,*p,CWP_SKIPINVISIBLE|CWP_SKIPDISABLED|CWP_SKIPTRANSPARENT);
        if(!next||next==h)break;
        MapWindowPoints(h,next,p,1);h=next;
    }
    DWORD pid=0;GetWindowThreadProcessId(h,&pid);
    if(pid!=owner)exit(4);
    return h;
}
static void send_window(HWND h,UINT message,WPARAM flags,POINT p) {
    DWORD_PTR result;
    last_point=p;
    if(!untouched()){fprintf(stderr,"user input state changed; stopped\n");exit(6);}
    if(!SendMessageTimeoutA(h,message,flags,MAKELPARAM(p.x,p.y),SMTO_ABORTIFHUNG|SMTO_ERRORONEXIT,1000,&result)) {
        fprintf(stderr,"message timeout/failure; partial effect possible\n");exit(5);
    }
    if(message==WM_LBUTTONDOWN)pressed_window=h;
    if(message==WM_LBUTTONUP)pressed_window=NULL;
}
int main(int argc,char **argv) {
    if(argc!=4&&argc!=6)return 1;
    if(strcmp(argv[1],"click")&&strcmp(argv[1],"drag"))return 1;
    expected_title=getenv("LAD_REVU_TITLE");
    if(!expected_title || !*expected_title)return 2;
    SetProcessDPIAware();EnumWindows(find,0);
    if(!root)return 2;
    const char *expected_hwnd=getenv("LAD_EXPECT_HWND"), *expected_pid=getenv("LAD_EXPECT_WINPID");
    if(!expected_hwnd||!expected_pid || (ULONG_PTR)root!=strtoull(expected_hwnd,NULL,16) || owner!=strtoul(expected_pid,NULL,10))return 4;
    atexit(cleanup_button);
    initial_foreground=GetForegroundWindow();GetCursorPos(&initial_cursor);
    RECT rect;GetClientRect(root,&rect);
    POINT p={atoi(argv[2]),atoi(argv[3])},end=p;
    if(argc==6){end.x=atoi(argv[4]);end.y=atoi(argv[5]);}
    if(!PtInRect(&rect,p)||!PtInRect(&rect,end))return 4;
    POINT local=p;HWND h=resolve(&local);
    printf("root=%p target=%p pid=%lu start=%ld,%ld foreground=%p\n",root,h,owner,local.x,local.y,initial_foreground);
    send_window(h,WM_MOUSEMOVE,0,local);
    send_window(h,WM_LBUTTONDOWN,MK_LBUTTON,local);
    POINT last=local;
    if(argc==6) {
        MapWindowPoints(root,h,&end,1);
        for(int i=1;i<=20;i++) {
            last.x=local.x+(end.x-local.x)*i/20;last.y=local.y+(end.y-local.y)*i/20;
            send_window(h,WM_MOUSEMOVE,MK_LBUTTON,last);Sleep(12);
        }
    }
    send_window(h,WM_LBUTTONUP,0,last);
    Sleep(100);
    printf("foreground_unchanged=%d pointer_unchanged=%d\n",GetForegroundWindow()==initial_foreground,untouched());
    return untouched()?0:6;
}
