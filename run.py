"""Local launcher. Deliberately no public deployment switch."""
import os, sys, threading, webbrowser
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
if __name__=='__main__':
    try:
        import uvicorn
        from backend.main import app
    except (ImportError,OSError) as exc:
        print('Startup failed:',exc)
        print('Run START_WINDOWS.bat. For a Windows Application Control block, ask the administrator to review the exact binary; do not disable protection.')
        sys.exit(1)
    if '--no-browser' not in sys.argv:
        threading.Timer(1.5,lambda:webbrowser.open('http://127.0.0.1:8765')).start()
    uvicorn.run(app,host='127.0.0.1',port=8765,log_level='info',loop='asyncio',http='h11')
