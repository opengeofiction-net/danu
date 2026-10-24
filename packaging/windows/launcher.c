/*
 * Danu.exe: what the Start menu runs. It finds the tree it sits at the top
 * of, points GDAL and PROJ at their data there, and starts the editor with
 * the tree's own pythonw - no console, nothing taken from the machine's PATH
 * ahead of the tree. The arguments it was given are passed on.
 *
 * A launcher rather than a shortcut to pythonw: the taskbar groups and the
 * window carries Danu's icon, and a mapper who goes looking finds Danu.exe
 * rather than an interpreter.
 */
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

#define LONG_ENOUGH 32768

static wchar_t root[MAX_PATH];

static void set(const wchar_t *name, const wchar_t *under)
{
    wchar_t v[MAX_PATH * 2];
    swprintf(v, MAX_PATH * 2, L"%ls\\%ls", root, under);
    SetEnvironmentVariableW(name, v);
}

static int fail(const wchar_t *what)
{
    DWORD err = GetLastError();     /* before anything below can set it */
    wchar_t msg[LONG_ENOUGH];
    swprintf(msg, LONG_ENOUGH, L"Danu could not start: %ls (error %lu).\n\nReinstalling it may help.",
             what, err);
    MessageBoxW(NULL, msg, L"Danu", MB_ICONERROR | MB_OK);
    return 1;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR args, int show)
{
    static wchar_t path[LONG_ENOUGH], cmd[LONG_ENOUGH], exe[MAX_PATH * 2];
    wchar_t *slash;
    DWORD n;
    STARTUPINFOW si = {0};
    PROCESS_INFORMATION pi;
    (void) inst; (void) prev; (void) show;

    n = GetModuleFileNameW(NULL, root, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return fail(L"its own path is too long");
    slash = wcsrchr(root, L'\\');
    if (!slash) return fail(L"its own path has no directory");
    *slash = 0;

    /* the tree's bin first, so its DLLs are the ones found; a PATH too long
     * to have the tree put in front of it is replaced by the tree alone,
     * which is all the editor needs */
    n = GetEnvironmentVariableW(L"PATH", path, LONG_ENOUGH);
    if (n == 0 || n >= LONG_ENOUGH ||
            swprintf(cmd, LONG_ENOUGH, L"%ls\\bin;%ls", root, path) < 0)
        swprintf(cmd, LONG_ENOUGH, L"%ls\\bin", root);
    SetEnvironmentVariableW(L"PATH", cmd);
    set(L"GDAL_DATA", L"share\\gdal");
    set(L"PROJ_DATA", L"share\\proj");
    /* the tree's CA certificates as well as the Windows store's, which holds
     * only the roots Windows' own TLS has fetched so far (#262) */
    if (!GetEnvironmentVariableW(L"SSL_CERT_FILE", NULL, 0) && !GetEnvironmentVariableW(L"SSL_CERT_DIR", NULL, 0))
        set(L"SSL_CERT_FILE", L"ssl\\cacert.pem");
    /* a PYTHONHOME or PYTHONPATH meant for another Python would be read */
    SetEnvironmentVariableW(L"PYTHONHOME", NULL);
    SetEnvironmentVariableW(L"PYTHONPATH", NULL);

    swprintf(exe, MAX_PATH * 2, L"%ls\\bin\\pythonw.exe", root);
    if (swprintf(cmd, LONG_ENOUGH, L"\"%ls\" -m danu.ui %ls", exe, args ? args : L"") < 0) {
        SetLastError(ERROR_FILENAME_EXCED_RANGE);
        return fail(L"what it was asked to open is too long");
    }
    si.cb = sizeof si;
    if (!CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi))
        return fail(L"the bundled Python would not start");
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
