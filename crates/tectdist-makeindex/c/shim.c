/* In-process MakeIndex entry shim.
 *
 * The pinned MakeIndex sources report fatal conditions through EXIT (an exit()
 * macro), which would terminate the host process when embedded. The build
 * renames the `main` and `exit` symbols; this shim provides the renamed exit
 * and a setjmp-based run entry that converts EXIT calls into return values.
 *
 * The jump buffer makes the embedded runner non-reentrant; callers must
 * serialise invocations (the Rust wrapper holds a mutex).
 */
#include <setjmp.h>

int makeindex_main(int argc, char **argv);
void tectdist_makeindex_exit(int code);

static jmp_buf tectdist_jmp;

int tectdist_makeindex_run(int argc, char **argv)
{
    int val = setjmp(tectdist_jmp);
    if (val != 0) {
        /* Fatal or terminal path: MakeIndex called EXIT(code); the shim
         * stored code + 1 so a plain EXIT(0) stays distinguishable. */
        return val - 1;
    }
    return makeindex_main(argc, argv);
}

void tectdist_makeindex_exit(int code)
{
    longjmp(tectdist_jmp, code == 2147483647 ? code : code + 1);
}
