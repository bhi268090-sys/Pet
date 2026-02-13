import time
import recon
import sys

print("Verifying Phase 5 (Cleanup/Stabilization) recon.py...")

# Initialization check
try:
    r = recon.GhostRecon()
    print("PASS: Initialization successful.")
except Exception as e:
    print(f"FAIL: Crash during initialization: {e}")
    sys.exit(1)

# Check standard methods
print("Testing standard data gathering methods...")
try:
    ram = r.get_ram()
    print(f"RAM: {ram}")
    
    cpu = r.get_cpu()
    print(f"CPU: {cpu}")
    
    model = r.get_model()
    print(f"Model: {model}")
    
    upt = r.get_uptime()
    print(f"Uptime: {upt}")

    print("PASS: Standard methods are functional.")
except Exception as e:
    print(f"FAIL: Crash during method execution: {e}")

print("Verification complete.")
