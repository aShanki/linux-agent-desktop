#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HWND root;
static const char *expected_title;
static DWORD owner;
static BOOL CALLBACK find(HWND h, LPARAM unused) {
    char title[512];
    GetWindowTextA(h,title,sizeof title);
    if(strstr(title,expected_title) && strstr(title,"Bluebeam Revu x64")) {
        if(root) { fprintf(stderr,"ambiguous target\n"); exit(3); }
        root=h; GetWindowThreadProcessId(root,&owner);
    }
    return TRUE;
}
static BOOL CALLBACK describe(HWND h, LPARAM unused) {
    char klass[256];RECT rect;DWORD pid=0;
    GetClassNameA(h,klass,sizeof klass);GetWindowRect(h,&rect);GetWindowThreadProcessId(h,&pid);
    printf("hwnd=%p parent=%p pid=%lu visible=%d rect=%ld,%ld,%ld,%ld class=%s\n",h,GetParent(h),pid,IsWindowVisible(h),rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top,klass);
    return TRUE;
}
int main(int argc,char **argv) {
    expected_title=getenv("LAD_REVU_TITLE");
    if(!expected_title || !*expected_title)return 2;
    SetProcessDPIAware();
    EnumWindows(find,0);
    if(!root){fprintf(stderr,"test document not found\n");return 2;}
    printf("root=%p pid=%lu foreground=%p\n",root,owner,GetForegroundWindow());
    if(argc==2 && !strcmp(argv[1],"--identity"))return 0;
    describe(root,0);EnumChildWindows(root,describe,0);
    return 0;
}
