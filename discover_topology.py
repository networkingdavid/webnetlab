#!/usr/bin/env python3
"""
Network topology discovery script.
SSHes into jump server, then telnets to each Cisco IOS device
to collect CDP neighbors, interfaces, and hostname.
"""

import paramiko
import time
import json
import socket

JUMP_HOST = "192.168.1.90"
JUMP_USER = "david"
JUMP_PASS = "reloaded"
JUMP_PORT = 22

DEVICES = [
    "192.168.1.18",
    "192.168.170.2",
    "192.168.170.3",
    "192.168.170.4",
    "192.168.170.5",
]

TELNET_PASS = "reloaded"
ENABLE_PASS = "cisco"


def recv_until(shell, endings, timeout=10):
    """Read from shell until one of the ending strings appears or timeout."""
    buf = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if shell.recv_ready():
            chunk = shell.recv(4096).decode("utf-8", errors="replace")
            buf += chunk
            for end in endings:
                if end in buf:
                    return buf
        else:
            time.sleep(0.15)
    return buf


def send_cmd(shell, cmd, endings=None, timeout=10):
    """Send a command and wait for a prompt."""
    if endings is None:
        endings = ["#", ">", "$ "]
    shell.send(cmd + "\n")
    return recv_until(shell, endings, timeout)


def collect_device_info(shell, ip):
    """Telnet to device through jump shell and collect topology data."""
    results = {}

    print(f"  -> Opening telnet to {ip}")
    shell.send(f"telnet {ip}\n")

    # Wait for password or username prompt
    banner = recv_until(shell, ["Password:", "password:", "Username:", "username:", "Login:"], timeout=8)
    results["banner"] = banner

    if "Username" in banner or "username" in banner or "Login" in banner:
        shell.send(JUMP_USER + "\n")
        banner += recv_until(shell, ["Password:", "password:"], timeout=5)

    if "Password" in banner or "password" in banner:
        shell.send(TELNET_PASS + "\n")
        prompt = recv_until(shell, ["#", ">", "Password:", "password:"], timeout=6)
        results["login"] = prompt
    else:
        results["login"] = banner

    # Second password attempt if still prompted
    if "Password" in results.get("login", "") or "password" in results.get("login", ""):
        shell.send(TELNET_PASS + "\n")
        results["login2"] = recv_until(shell, ["#", ">"], timeout=5)

    # Enable mode
    shell.send("enable\n")
    en_prompt = recv_until(shell, ["Password:", "password:", "#"], timeout=5)
    if "Password" in en_prompt or "password" in en_prompt:
        shell.send(ENABLE_PASS + "\n")
        recv_until(shell, ["#"], timeout=5)

    # Disable paging
    send_cmd(shell, "terminal length 0", timeout=5)

    # --- Gather show commands ---
    results["hostname"] = send_cmd(shell, "show running-config | include hostname", timeout=8)
    results["cdp_detail"] = send_cmd(shell, "show cdp neighbors detail", timeout=15)
    results["ip_int_brief"] = send_cmd(shell, "show ip interface brief", timeout=8)
    results["interfaces_desc"] = send_cmd(shell, "show interfaces description", timeout=8)
    results["lldp_neighbors"] = send_cmd(shell, "show lldp neighbors detail", timeout=10)

    # Exit telnet
    shell.send("exit\n")
    time.sleep(0.5)
    # Send telnet escape just in case
    shell.send("\x1d")
    time.sleep(0.3)
    shell.send("quit\n")
    recv_until(shell, ["$ ", "# ", "> "], timeout=5)

    return results


def main():
    results = {}

    # Connect to jump server
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[*] Connecting to jump server {JUMP_HOST} as {JUMP_USER}...")

    try:
        client.connect(
            JUMP_HOST, port=JUMP_PORT,
            username=JUMP_USER, password=JUMP_PASS,
            look_for_keys=False, allow_agent=False,
            timeout=15
        )
    except Exception as e:
        print(f"[!] SSH connection failed: {e}")
        return

    shell = client.invoke_shell(width=250, height=50)
    time.sleep(2)
    # Drain welcome banner
    banner = recv_until(shell, ["$ ", "# ", "> "], timeout=8)
    print(f"[*] Jump server shell ready. Banner snippet: {banner[-200:]!r}")

    for ip in DEVICES:
        print(f"\n[*] Collecting from {ip}...")
        try:
            info = collect_device_info(shell, ip)
            results[ip] = info
            print(f"  [+] Done: {ip}")
        except Exception as e:
            results[ip] = {"error": str(e)}
            print(f"  [!] Error on {ip}: {e}")
        time.sleep(0.5)

    client.close()
    print("\n[*] All devices polled. Saving raw data...")

    with open("topology_raw.json", "w") as f:
        json.dump(results, f, indent=2)
    print("[*] Saved topology_raw.json")

    # Print per-device summary
    for ip, data in results.items():
        print(f"\n{'='*60}\nDevice: {ip}")
        if "error" in data:
            print(f"  ERROR: {data['error']}")
        else:
            for k, v in data.items():
                print(f"\n-- {k} --\n{v}")


if __name__ == "__main__":
    main()
