#ifndef GRAPHCORE_C_API_H
#define GRAPHCORE_C_API_H
#include <stddef.h>
#if defined(_WIN32)
# if defined(GRAPHCORE_BUILD_SHARED)
#  define GC_API __declspec(dllexport)
# else
#  define GC_API __declspec(dllimport)
# endif
#else
# define GC_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* One handle per graph/run; handles must not be used concurrently.
   Strings are UTF-8, NUL terminated. Returned strings live until the next call.
   Callback state is hex wire format; callback and user data must outlive handle. */
typedef struct gc_handle gc_handle;
typedef int (*gc_callback)(const char* state, int resumed, const char* response,
                           void* reply, void* user_data);
typedef void (*gc_event_callback)(const char* type, const char* node, void* user_data);
/* Set observer before running; cancel is the only method safe during gc_run. */
GC_API int gc_set_observer(gc_handle*, gc_event_callback, void* user_data);
GC_API void gc_cancel(gc_handle*);
/* Native equality branch; values use the caller's state encoding. */
GC_API int gc_add_condition(gc_handle*, const char* name, const char* key,
                            const char* expected, const char* yes, const char* no);
GC_API gc_handle* gc_create(const char* version);
GC_API void gc_destroy(gc_handle*);
GC_API const char* gc_error(gc_handle*);
GC_API int gc_add_node(gc_handle*, const char* name, gc_callback, void* user_data, unsigned retries);
GC_API int gc_add_edge(gc_handle*, const char* source, const char* target);
GC_API int gc_set_entry(gc_handle*, const char* name);
/* checkpoint=NULL disables persistence; response=NULL means no resume response. */
GC_API int gc_run(gc_handle*, const char* initial_wire, const char* checkpoint,
                  int resume, const char* response, size_t max_steps);
GC_API int gc_inspect_checkpoint(gc_handle*, const char* path);
GC_API const char* gc_result(gc_handle*);
GC_API const char* gc_prompt(gc_handle*);
GC_API int gc_suspended(gc_handle*);
GC_API size_t gc_steps(gc_handle*);
/* Reply helpers return -1 on failure; callback must propagate failure. */
GC_API int gc_reply_update(void*, const char* key, const char* value);
GC_API int gc_reply_next(void*, const char* target);
GC_API int gc_reply_suspend(void*, const char* prompt);
GC_API int gc_reply_error(void*, const char* message);
#ifdef __cplusplus
}
#endif
#endif
