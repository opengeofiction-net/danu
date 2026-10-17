/*
 * Danu.app/Contents/MacOS/Danu: what the Finder and the Dock run. It finds
 * the app it sits in, points GDAL and PROJ at their data there and Python's
 * TLS at the app's CA certificates where the machine names none, and runs
 * the editor in this process with the app's own Python.
 *
 * In this process, and not by starting the app's python3: macOS names an
 * application, in its menu bar and its Dock, after the bundle its
 * executable sits in, and the executable is this one. The app's python3,
 * under Contents/Resources/bin, would be "python3". So Python is embedded,
 * from the app's libpython, with the app's Resources as its home; and
 * sys.executable is still that python3, which multiprocessing starts its
 * workers with - the sea mask's are spawned.
 *
 *   Danu [ARGS...]               the editor, ARGS passed on as danu's own
 *   Danu --python SCRIPT [ARGS]  the app's Python on SCRIPT instead, for a
 *                                check of the app made from outside it, as
 *                                the AppImage's AppRun --python is
 */
#include <Python.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char res[PATH_MAX + 16];     /* the app's Contents, and /Resources */

static void under(const char *name, const char *rel, int only_if_unset)
{
    char v[PATH_MAX * 2];
    if (only_if_unset && getenv(name))
        return;
    snprintf(v, sizeof v, "%s/%s", res, rel);
    setenv(name, v, 1);
}

static int fail(const char *what, PyStatus st)
{
    fprintf(stderr, "Danu could not start: %s%s%s\n", what,
            st.err_msg ? ": " : "", st.err_msg ? st.err_msg : "");
    return 1;
}

int main(int argc, char **argv)
{
    char self[PATH_MAX], real[PATH_MAX], *slash;
    uint32_t n = sizeof self;
    PyConfig config;
    PyStatus st;
    int prog = 0;                   /* sys.argv[0]: the editor's, or the script */

    if (_NSGetExecutablePath(self, &n) != 0 || !realpath(self, real)) {
        fprintf(stderr, "Danu could not start: it cannot find itself\n");
        return 1;
    }
    /* .../Danu.app/Contents/MacOS/Danu -> .../Danu.app/Contents/Resources */
    slash = strrchr(real, '/');
    if (slash) *slash = 0;
    slash = strrchr(real, '/');
    if (!slash) {
        fprintf(stderr, "Danu could not start: %s is not inside an app\n", real);
        return 1;
    }
    *slash = 0;
    snprintf(res, sizeof res, "%s/Resources", real);

    under("GDAL_DATA", "share/gdal", 0);
    under("PROJ_DATA", "share/proj", 0);
    /* the app's OpenSSL was built for a prefix that is not here; macOS keeps
     * its own CA certificates in the keychain, which OpenSSL cannot read */
    if (!getenv("SSL_CERT_DIR"))
        under("SSL_CERT_FILE", "ssl/cacert.pem", 1);
    /* a PYTHONHOME or PYTHONPATH meant for another Python would be read */
    unsetenv("PYTHONHOME");
    unsetenv("PYTHONPATH");

    PyConfig_InitIsolatedConfig(&config);
    config.parse_argv = 0;          /* danu's arguments are danu's, not Python's */
    config.write_bytecode = 0;      /* compiled when the app was built; the app may be read-only */
    st = PyConfig_SetBytesString(&config, &config.home, res);
    if (PyStatus_Exception(st)) return fail("its Python's home", st);
    {
        char exe[PATH_MAX * 2];
        snprintf(exe, sizeof exe, "%s/bin/python3", res);
        st = PyConfig_SetBytesString(&config, &config.executable, exe);
        if (PyStatus_Exception(st)) return fail("its Python", st);
    }

    if (argc >= 2 && strcmp(argv[1], "--python") == 0) {
        if (argc < 3) {
            fprintf(stderr, "Danu: --python wants a script to run\n");
            PyConfig_Clear(&config);
            return 2;
        }
        st = PyConfig_SetBytesString(&config, &config.run_filename, argv[2]);
        if (PyStatus_Exception(st)) return fail("the script", st);
        prog = 2;
    } else {
        st = PyConfig_SetString(&config, &config.run_module, L"danu.ui");
        if (PyStatus_Exception(st)) return fail("the editor", st);
    }
    /* sys.argv: the program, then what it was given - less the -psn_ a
     * Finder launch added on old macOS, which danu's parser would refuse */
    {
        char **args = calloc((size_t) argc + 1, sizeof *args);
        int m = 0;
        if (!args) { fprintf(stderr, "Danu could not start: out of memory\n"); return 1; }
        args[m++] = argv[prog];
        for (int i = prog + 1; i < argc; i++)
            if (strncmp(argv[i], "-psn_", 5) != 0)
                args[m++] = argv[i];
        st = PyConfig_SetBytesArgv(&config, m, args);
        free(args);
        if (PyStatus_Exception(st)) return fail("its arguments", st);
    }

    st = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(st)) return fail("its Python", st);
    return Py_RunMain();
}
