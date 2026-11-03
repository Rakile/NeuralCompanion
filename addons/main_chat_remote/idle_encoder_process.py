"""Process-lifetime containment for the private Windows idle-catalog worker."""
import sys


def contain_encoder_children():
    """A catalog crash must release its FFmpeg descendants, not leave GPU work.

    Called once inside the short-lived catalog process before any encode. The
    non-inheritable job handle intentionally lives until process exit; Windows
    closes it on normal exit, cancellation or crash and kills remaining members.
    POSIX workers use the process group owned by IdleLoopWorker instead.
    """
    if sys.platform!='win32':
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
            ('flags',wintypes.DWORD),('minimum_working_set',ctypes.c_size_t),
            ('maximum_working_set',ctypes.c_size_t),('active_processes',wintypes.DWORD),
            ('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]

    class IOCounters(ctypes.Structure):
        _fields_=[(name,ctypes.c_ulonglong) for name in
            ('read_operations','write_operations','other_operations','read_bytes','write_bytes','other_bytes')]

    class ExtendedLimits(ctypes.Structure):
        _fields_=[('basic',BasicLimits),('io',IOCounters),('process_memory',ctypes.c_size_t),
            ('job_memory',ctypes.c_size_t),('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]

    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.SetInformationJobObject.restype=wintypes.BOOL
    kernel.GetCurrentProcess.argtypes=[]
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    job=kernel.CreateJobObjectW(None,None)
    if not job:
        raise ValueError('Idle encoder containment unavailable')
    limits=ExtendedLimits()
    limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job,kernel.GetCurrentProcess())):
        kernel.CloseHandle(job)
        raise ValueError('Idle encoder containment unavailable')
    return job
