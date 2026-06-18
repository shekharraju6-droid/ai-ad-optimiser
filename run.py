import os
import sys
import subprocess
import webbrowser
import time

def main():
    print("====================================================")
    print("             AdOptima AI - Google Ads               ")
    print("             Optimization Assistant                 ")
    print("====================================================")
    
    # 1. Install dependencies check
    print("[*] Checking dependencies...")
    try:
        import fastapi
        import uvicorn
        import google.generativeai
        import pydantic
        import pandas
        print("[+] All core dependencies are available.")
    except ImportError:
        print("[!] Missing dependencies. Installing via pip...")
        try:
            requirements_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", requirements_path])
            print("[+] Dependencies installed successfully.")
        except Exception as e:
            print(f"[-] Auto-installation failed: {e}")
            print("Please run manually: pip install -r requirements.txt")
            sys.exit(1)
            
    # 2. Start Uvicorn backend server
    print("[*] Starting backend server on http://127.0.0.1:8000...")
    
    # Get current directory and add backend to pythonpath
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    cmd = [
        sys.executable, 
        "-m", 
        "uvicorn", 
        "backend.app:app", 
        "--host", 
        "127.0.0.1", 
        "--port", 
        "8000",
        "--reload"
    ]
    
    try:
        # Run backend server in background
        proc = subprocess.Popen(cmd, cwd=cwd)
        time.sleep(2.0) # Give Uvicorn 2 seconds to bind to the port
        
        # Open web dashboard
        print("[*] Launching dashboard in your browser...")
        webbrowser.open("http://127.0.0.1:8000")
        
        # Block on the server subprocess to keep console alive and print outputs
        proc.wait()
    except KeyboardInterrupt:
        print("\n[*] Shutting down AdOptima AI. Goodbye!")
    except Exception as e:
        print(f"[-] Failed to launch server: {e}")

if __name__ == "__main__":
    main()
