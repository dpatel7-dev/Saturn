"""
SATURN — Groq-powered AI console for Google Colab
=================================================
Install & run — paste these two lines into any Colab cell:

    !wget -q https://dpatel7-dev.github.io/saturn/saturn.py -O saturn.py
    %run saturn.py

First run launches the Setup Wizard (API key + settings).
Re-run the wizard anytime with the /setup command, or force it with:

    %run saturn.py setup

AUTO-UPDATE: on every boot, Saturn checks GitHub for a newer copy of
itself. If anything changed, it installs the new version and relaunches
automatically with your saved settings. You can also trigger a check
manually with the /update command.

Settings are saved to /content/saturn_config.json for this runtime.
Note: Colab wipes /content when the runtime resets, so for a permanent
key, add GROQ_API_KEY in Colab Secrets (key icon in the left sidebar)
and the wizard will find it automatically.
"""

import os, sys, time, json, re, subprocess, hashlib, urllib.request, urllib.parse
from getpass import getpass
from IPython import get_ipython

SATURN_VERSION = '1.4'
REQUIRED_PACKAGES = ['groq', 'colorama']
CONFIG_PATH = '/content/saturn_config.json'

# Where Saturn looks for new versions of itself. It tries these in
# order and uses the first one that responds. IMPORTANT: if you ever
# rename your repo or GitHub username, update BOTH addresses here.
UPDATE_URLS = [
    'https://dpatel7-dev.github.io/saturn/saturn.py',
    'https://raw.githubusercontent.com/dpatel7-dev/saturn/main/saturn.py',
]

DEFAULT_CONFIG = {
    'engine': '1',            # key into MODELS below
    'temperature': 0.1,       # 0.0 = precise, 1.0 = creative
    'show_logo': True,        # boot animation on/off
    'api_key_source': 'secrets',  # 'secrets' or 'manual'
    'api_key': ''             # only stored when manual + user consents
}

# ────────────────────────────────────────────────────────────
# STARTUP SCRIPT
# Verifies the environment and installs missing packages
# before anything else is imported.
# ────────────────────────────────────────────────────────────

def _startup_check_colab():
    """Make sure we are actually inside Google Colab."""
    try:
        import google.colab  # noqa: F401
        print('[saturn-startup] * Google Colab environment detected')
    except ImportError:
        sys.exit(
            '\n[saturn-startup] x Saturn only runs inside Google Colab.\n'
            'It needs Colab\'s kernel to read/write notebook cells.\n'
            'Open https://colab.research.google.com and run it there.'
        )

def _startup_install_packages():
    """Quietly install any missing dependencies."""
    import importlib.util
    missing = [p for p in REQUIRED_PACKAGES if importlib.util.find_spec(p) is None]
    if not missing:
        print('[saturn-startup] * All dependencies already installed')
        return
    print(f'[saturn-startup] ... Installing: {", ".join(missing)}')
    try:
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-q', *missing],
            check=True
        )
        print('[saturn-startup] * Dependencies installed')
    except subprocess.CalledProcessError:
        sys.exit('[saturn-startup] x pip install failed. Check your internet connection and re-run the cell.')

# Environment check + dependency install must happen BEFORE the
# imports below, otherwise they would fail on a fresh Colab runtime.
_startup_check_colab()
_startup_install_packages()

# ────────────────────────────────────────────────────────────
# AUTO-UPDATE
# Compares this running file against the copy on GitHub.
# Any committed change (even one character) triggers an update.
# ────────────────────────────────────────────────────────────

def _fetch_remote_saturn():
    """Download the latest saturn.py from GitHub.
    Returns (source_code, version) or (None, None) if unreachable."""
    for base in UPDATE_URLS:
        try:
            # The ?nocache= part defeats GitHub's CDN cache so fresh
            # commits are picked up quickly instead of minutes later.
            url = base + '?nocache=' + str(int(time.time()))
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                src = r.read().decode('utf-8')
            m = re.search(r"SATURN_VERSION\s*=\s*'([^']+)'", src)
            # Sanity check: only accept files that really look like Saturn,
            # so a 404 page or wrong file can never overwrite the script.
            if m and 'def start_saturn_console' in src:
                return src, m.group(1)
        except Exception:
            continue
    return None, None

def check_for_updates():
    """Install + relaunch if GitHub has a different version.
    Returns True if an update took over (caller should stop running)."""
    label = '[saturn-update]'
    local_path = os.path.abspath(globals().get('__file__', '/content/saturn.py'))
    try:
        with open(local_path, encoding='utf-8') as f:
            local_src = f.read()
    except Exception:
        print(f'{label} ! Could not read local file, skipping update check.')
        return False

    remote_src, remote_ver = _fetch_remote_saturn()
    if remote_src is None:
        print(f'{label} ! Could not reach GitHub, skipping update check.')
        return False

    local_hash = hashlib.sha256(local_src.encode()).hexdigest()
    remote_hash = hashlib.sha256(remote_src.encode()).hexdigest()
    if local_hash == remote_hash:
        print(f'{label} * Saturn is up to date (v{SATURN_VERSION})')
        return False

    print(f'{label} * Changes detected on GitHub (remote v{remote_ver}, running v{SATURN_VERSION})')
    try:
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(remote_src)
    except Exception as e:
        print(f'{label} x Could not write the update: {e}')
        return False

    print(f'{label} * Update installed — relaunching with your saved settings ...\n')
    os.environ['SATURN_JUST_UPDATED'] = '1'   # stops the new copy re-checking instantly
    time.sleep(1.0)
    try:
        get_ipython().run_line_magic('run', local_path)
    except Exception as e:
        print(f'{label} ! Auto-relaunch failed ({e}). Re-run this cell to start v{remote_ver}.')
    return True

from colorama import Fore, Style, init
init(strip=False, autoreset=True)
from groq import Groq
from google.colab import userdata, output
from google.colab import _message as colab_message

# ────────────────────────────────────────────────────────────
# SETTINGS + SETUP WIZARD
# ────────────────────────────────────────────────────────────

MODELS = {'1': 'llama-3.1-8b-instant', '2': 'llama-3.3-70b-versatile'}
MODEL_NOTES = {'1': 'fastest responses', '2': 'smartest answers'}
BORDER = '=' * 56
THIN = '-' * 56

def load_config():
    """Load saved settings from this runtime, if any."""
    try:
        with open(CONFIG_PATH) as f:
            saved = json.load(f)
        return {**DEFAULT_CONFIG, **saved}
    except Exception:
        return None

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False

def _get_secret_key():
    """Read GROQ_API_KEY from Colab Secrets, or return None."""
    try:
        return userdata.get('GROQ_API_KEY') or None
    except Exception:
        return None

def _validate_key(key):
    """Ping Groq with the key to confirm it actually works."""
    try:
        Groq(api_key=key).models.list()
        return True
    except Exception:
        return False

def _ask(prompt, default=''):
    """Input with a default value when the user just presses Enter."""
    val = input(Fore.WHITE + prompt + Style.RESET_ALL).strip()
    return val if val else default

def _ask_yes_no(prompt, default_yes=True):
    hint = '[Y/n]' if default_yes else '[y/N]'
    val = _ask(f'{prompt} {hint}: ', 'y' if default_yes else 'n')
    return val.lower().startswith('y')

def run_setup_wizard():
    """Formal first-run configuration. Returns (config, api_key)."""
    config = dict(DEFAULT_CONFIG)

    print(Fore.RED + Style.BRIGHT + BORDER)
    print(Fore.WHITE + Style.BRIGHT + '            S A T U R N   S E T U P   v' + SATURN_VERSION)
    print(Fore.RED + Style.BRIGHT + BORDER)
    print(Fore.LIGHTBLACK_EX + ' This wizard configures Saturn for this runtime.')
    print(Fore.LIGHTBLACK_EX + ' Re-run it anytime with /setup or: %run saturn.py setup')
    print(Fore.RED + THIN + '\n')

    # ── Step 1: API key ──────────────────────────────────────
    print(Fore.CYAN + Style.BRIGHT + '[Step 1/4] Groq API key')
    api_key = None
    secret_key = _get_secret_key()
    if secret_key:
        print(Fore.GREEN + '  Found GROQ_API_KEY in Colab Secrets.')
        if _ask_yes_no('  Use this key?'):
            print('  Verifying key with Groq ...')
            if _validate_key(secret_key):
                print(Fore.GREEN + '  Key verified.')
                api_key = secret_key
                config['api_key_source'] = 'secrets'
            else:
                print(Fore.RED + '  That key was rejected by Groq. Let\'s enter one manually.')
    else:
        print(Fore.YELLOW + '  No GROQ_API_KEY found in Colab Secrets.')
        print(Fore.LIGHTBLACK_EX + '  Tip: add it there (key icon, left sidebar) to skip this step forever.')

    if not api_key:
        for attempt in range(3):
            key = getpass('  Paste your Groq API key (input hidden): ').strip()
            if not key:
                print(Fore.RED + '  Nothing entered, try again.')
                continue
            print('  Verifying key with Groq ...')
            if _validate_key(key):
                print(Fore.GREEN + '  Key verified.')
                api_key = key
                config['api_key_source'] = 'manual'
                if _ask_yes_no('  Remember this key for the rest of this runtime?'):
                    config['api_key'] = key
                break
            print(Fore.RED + '  Key rejected by Groq. Check it at https://console.groq.com/keys')
        if not api_key:
            sys.exit('\n[saturn-setup] x No working API key after 3 attempts. Setup cancelled.')

    # ── Step 2: Default engine ───────────────────────────────
    print(Fore.CYAN + Style.BRIGHT + '\n[Step 2/4] Default engine')
    for num, name in MODELS.items():
        print(f'  {num}) {name}  ({MODEL_NOTES[num]})')
    while True:
        choice = _ask('  Choice [1]: ', '1')
        if choice in MODELS:
            config['engine'] = choice
            break
        print(Fore.RED + '  Please enter one of: ' + ', '.join(MODELS))

    # ── Step 3: Temperature ──────────────────────────────────
    print(Fore.CYAN + Style.BRIGHT + '\n[Step 3/4] Creativity (temperature)')
    print(Fore.LIGHTBLACK_EX + '  0.0 = precise and factual, 1.0 = loose and creative')
    while True:
        raw = _ask('  Value between 0.0 and 1.0 [0.1]: ', '0.1')
        try:
            temp = float(raw)
            if 0.0 <= temp <= 1.0:
                config['temperature'] = temp
                break
        except ValueError:
            pass
        print(Fore.RED + '  Please enter a number between 0.0 and 1.0')

    # ── Step 4: Boot logo ────────────────────────────────────
    print(Fore.CYAN + Style.BRIGHT + '\n[Step 4/4] Boot logo')
    config['show_logo'] = _ask_yes_no('  Show the ASCII logo animation on startup?')

    # ── Save + summary ───────────────────────────────────────
    print(Fore.RED + '\n' + THIN)
    if save_config(config):
        print(Fore.GREEN + ' Settings saved to ' + CONFIG_PATH)
    else:
        print(Fore.YELLOW + ' Could not save settings file; using them for this session only.')
    print(Fore.WHITE + ' Engine: ' + MODELS[config['engine']]
          + '   Temperature: ' + str(config['temperature'])
          + '   Logo: ' + ('on' if config['show_logo'] else 'off'))
    print(Fore.RED + Style.BRIGHT + BORDER + '\n')
    time.sleep(0.8)
    return config, api_key

def resolve_api_key(config):
    """Get the working key according to saved settings, or None."""
    if config.get('api_key_source') == 'secrets':
        return _get_secret_key()
    return config.get('api_key') or None

# ────────────────────────────────────────────────────────────
# SATURN CORE
# ────────────────────────────────────────────────────────────

M = {'run': 0, 'lat': 0.0, 'spd': 0.0, 'err': 0, 'mood': 'Optimized'}

def dashboard(engine, temperature):
    print(Fore.RED + Style.BRIGHT + BORDER)
    print(Fore.WHITE + ' SYSTEM MONITOR   ::', Fore.GREEN + 'ONLINE')
    print(Fore.WHITE + ' CORE SENTIMENT   ::', Fore.MAGENTA + M['mood'])
    print(Fore.WHITE + ' ACTIVE ENGINE    ::', Fore.LIGHTBLACK_EX + engine)
    print(Fore.WHITE + ' TEMPERATURE      ::', Fore.CYAN + str(temperature))
    print(Fore.WHITE + ' LATENCY PROFILE  ::', Fore.CYAN + str(M['lat']) + 's  |  SPEED: ' + str(M['spd']) + ' w/s')
    print(Fore.WHITE + ' OPERATIONS RUN   ::', Fore.YELLOW + str(M['run']) + ' tasks  |  ERRORS: ' + Fore.RED + str(M['err']))
    print(Fore.RED + Style.BRIGHT + BORDER)
    print(Fore.LIGHTBLACK_EX + ' Commands: /status  /read  /clear  /engine <n>  /setup  /update  exit\n')

def web_search(query):
    print(Fore.CYAN + f"[web] Searching: {query} ...")
    try:
        # The "lite" endpoint matches the snippet regex below.
        url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote_plus(query)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
        text_snippets = re.findall(r"<td class=['\"]result-snippet['\"]>(.*?)</td>", html, re.DOTALL)[:3]
        clean_text = " ".join([re.sub(r'<.*?>', '', s) for s in text_snippets]).strip()
        print(Fore.GREEN + "[ok] Web search complete.")
        return clean_text if clean_text else "No search snippet found."
    except Exception as e:
        M['err'] += 1; return f"Search failed: {str(e)}"

def web_crawl(target_url):
    print(Fore.CYAN + f"[web] Crawling: {target_url} ...")
    try:
        if not target_url.startswith(('http://', 'https://')):
            target_url = 'https://' + target_url
        req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
        text = re.sub(r'<(script|style).*?>.*?</\1>', '', html, flags=re.DOTALL)
        text = re.sub(r'<.*?>', ' ', text)
        clean_text = re.sub(r'\s+', ' ', text).strip()[:1000]
        print(Fore.GREEN + "[ok] Page content cached.")
        return clean_text if clean_text else "Target web wrapper content body was empty."
    except Exception as e:
        M['err'] += 1; return f"Crawl wrapper error: {str(e)}"

def parse_json_safely(raw_text):
    try:
        json_match = re.search(r'(\{.*\}|\[.*\])', raw_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(1))
            return f"\n[Parser Success]: Structured layout data validated.\n{json.dumps(parsed, indent=2)}"
        return ""
    except json.JSONDecodeError as je:
        return f"\n[Parser Warning]: Malformed data layout detected: {str(je)}"

def get_notebook_cells():
    """Read the live notebook using Colab's real 'get_ipynb' request."""
    try:
        res = colab_message.blocking_request('get_ipynb', request='', timeout_sec=30)
        cells = res.get('ipynb', {}).get('cells', [])
        parsed = []
        for c in cells:
            src = c.get('source', [])
            if isinstance(src, list):
                src = ''.join(src)
            parsed.append({'type': c.get('cell_type'), 'content': src[:4000]})
        return parsed
    except Exception as e: return f"Kernel error: {str(e)}"

CELL_COUNTER = {'n': 0}

def create_new_cell(cell_type, content):
    """Prepare a ready-to-insert cell.

    Colab has no supported API for inserting cells from Python (the output
    area runs in a sandboxed frame), so Saturn does the next best thing:
    it saves the content to a file and hands the user a one-line %load
    command that pours it straight into a fresh cell.
    """
    CELL_COUNTER['n'] += 1
    fname = f"/content/saturn_cell_{CELL_COUNTER['n']}.py"
    body = content if cell_type == 'code' else '%%markdown\n' + content
    try:
        with open(fname, 'w') as f:
            f.write(body)
    except Exception as e:
        print(Fore.RED + f"[error] Could not save cell file: {e}")
        return
    # Harmless bonus attempt: some Jupyter frontends honor this and
    # insert the cell automatically. Colab may simply ignore it.
    try:
        get_ipython().set_next_input(body)
    except Exception:
        pass
    print(Fore.WHITE + Style.BRIGHT + '-' * 18 + f' generated {cell_type} cell ' + '-' * 18)
    print(Fore.CYAN + content)
    print(Fore.WHITE + Style.BRIGHT + '-' * 56)
    print(Fore.GREEN + f"[ok] Saved to {fname}")
    print(Fore.YELLOW + f"     To insert it: add a new cell below and run:  %load {fname}")

def append_autocomplete(text):
    # Colab's frontend has no cursor-injection API, so this now routes
    # through the same reliable cell-preparation flow.
    create_new_cell('code', text)

def run_ui_tool(text):
    M['run'] += 1
    url_match = re.search(r'\[TOOL:URL=(.*?)\]', text)
    if url_match: return f"[Web Crawl Results]: {web_crawl(url_match.group(1).strip())}"
    search_match = re.search(r'\[TOOL:SEARCH=(.*?)\]', text)
    if search_match: return f"[Web Search Results]: {web_search(search_match.group(1).strip())}"
    cell_match = re.search(r'\[CELL:(code|text)=(.*?)\].*', text, re.DOTALL)
    if cell_match: create_new_cell(cell_match.group(1), cell_match.group(2)); return "Cell injected."
    auto_match = re.search(r'\[AUTOCOMPLETE=(.*?)\]', text, re.DOTALL)
    if auto_match: append_autocomplete(auto_match.group(1)); return "Autocompletion completed."
    return ''

def animate_logo():
    """Satisfying line-burst animation sequence."""
    logo_lines = [
        r"███████╗ █████╗ ████████╗██╗   ██╗██████╗ ███╗   ██╗",
        r"██╔════╝██╔══██╗╚══██╔══╝██║   ██║██╔══██╗████╗  ██║",
        r"███████╗███████║   ██║   ██║   ██║██████╔╝██╔██╗ ██║",
        r"╚════██║██╔══██║   ██║   ██║   ██║██╔══██╗██║╚██╗██║",
        r"███████║██║  ██║   ██║   ╚██████╔╝██║  ██║██║ ╚████║",
        r"╚══════╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝"
    ]
    print(Fore.RED + Style.BRIGHT + BORDER)
    sys.stdout.flush()
    time.sleep(0.15)
    for line in logo_lines:
        print(Fore.RED + Style.BRIGHT + line)
        sys.stdout.flush()
        time.sleep(0.09)          # line-burst effect
    print(Fore.RED + Style.BRIGHT + BORDER + '\n')
    print(Fore.LIGHTBLACK_EX + '           booting saturn v' + SATURN_VERSION + ' ...')
    sys.stdout.flush()
    time.sleep(1.4)               # hold so the logo is actually seen

def start_saturn_console(api_key, config):
    client = Groq(api_key=api_key)

    SYSTEM_PROMPT = (
        f"You are Saturn v{SATURN_VERSION}, an autonomous assistant and an expert Python programmer. You MUST use tools when external data is needed, but only when necessary and always concisely summarize results.\n"
        "CRITICAL TOOL INSTRUCTIONS:\n"
        "- For real-time data like current weather, time, or dates: Use [TOOL:SEARCH=concise_query] and summarize the first relevant result *directly and completely*. Once a concise summary has been generated, *do not perform additional searches or re-evaluate the query* unless the user explicitly asks for more detail or a different query. Avoid diving into specific APIs or deep crawls unless explicitly asked.\n"
        "- Scrape specific web address/link directly: [TOOL:URL=://website.com]\n"
        "- Prepare a new notebook cell for the user: [CELL:code=content] or [CELL:text=content]. Saturn displays the content and gives the user a one-line %load command to insert it into their notebook.\n"
        "- When generating code, explain your reasoning, follow Python best practices (e.g., clear variable names, comments for complex logic), and consider error handling.\n"
        "- If the user asks for code improvements or debugging, analyze the provided code and suggest specific modifications with explanations.\n"
        "- If the user asks for code to be fixed, analyze the provided code, identify the issue, and provide specific modifications with clear explanations, adhering to Python best practices.\n"
        "- If you need more information to provide a good code solution, ask clarifying questions.\n"
        "When outputting raw data structures like stats or dictionaries, structure them in a clean JSON format block. Be concise and direct in your responses."
    )
    history = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    curr_model = MODELS[config['engine']]

    if config.get('show_logo', True):
        animate_logo()
        output.clear() # Clear output AFTER ASCII art animation
    dashboard(curr_model, config['temperature'])

    while True:
        print(Fore.RED + Style.BRIGHT + '🪐 saturn > ' + Style.RESET_ALL, end='')
        inp = input().strip()
        if inp.lower() in ['exit', 'quit']: break
        if inp == '/status': output.clear(); dashboard(curr_model, config['temperature']); continue
        if inp == '/update':
            if check_for_updates():
                return   # the new version ran and finished; retire this one
            continue
        if inp == '/setup':
            output.clear()
            config, new_key = run_setup_wizard()
            client = Groq(api_key=new_key)
            curr_model = MODELS[config['engine']]
            output.clear()
            dashboard(curr_model, config['temperature'])
            continue
        if inp == '/read': inp = f"Analyze my notebook cells: {json.dumps(get_notebook_cells())}"
        if inp == '/clear': history = [{'role': 'system', 'content': SYSTEM_PROMPT}]; output.clear(); print('Memory cleared.'); continue
        if inp.startswith('/engine '):
            model_num = inp.split(' ')[1]
            if model_num in MODELS:
                curr_model = MODELS[model_num]
                output.clear()
                print(Fore.GREEN + f"Engine switched to: {curr_model}")
                dashboard(curr_model, config['temperature'])
            else:
                print(Fore.RED + "Invalid model number. Available models:")
                for num, name in MODELS.items():
                    print(f"  {num}: {name}")
            continue
        if not inp: continue

        history = history + [{'role': 'user', 'content': inp}]
        loop_active = True
        while loop_active:
            t0 = time.time()
            stream = client.chat.completions.create(model=curr_model, messages=history, temperature=config['temperature'], stream=True)
            print(Fore.WHITE + 'saturn > ' + Style.RESET_ALL, end='')
            out = ''

            for chunk in stream:
                choices = getattr(chunk, 'choices', None)
                if choices is not None and isinstance(choices, list) and len(choices) > 0:
                    delta = getattr(choices[0], 'delta', None)
                    dt = getattr(delta, 'content', '') if delta else ''
                    if dt:
                        stream_color = Fore.GREEN + Style.BRIGHT if M['spd'] > 60 else Fore.CYAN + Style.BRIGHT
                        sys.stdout.write(stream_color + str(dt))
                        sys.stdout.flush()
                        out += str(dt)
            print()

            parsed_json_feedback = parse_json_safely(out)
            if parsed_json_feedback:
                print(Fore.YELLOW + parsed_json_feedback)

            dt = max(time.time() - t0, 0.001)
            M['lat'], M['spd'] = round(dt, 2), round(len(out.split()) / dt, 1)
            M['mood'] = 'Hyper-Efficiency Peak' if M['spd'] > 60 else 'Stable // Analytical'

            # --- Modified logic for history update and tool handling ---
            tool_match_obj = re.search(r'\[TOOL:(URL|SEARCH|CELL|AUTOCOMPLETE)=.*?(\]|$)', out, re.DOTALL)
            tool_res = run_ui_tool(out) # run_ui_tool still processes the first tool in 'out'

            if tool_match_obj:
                # If a tool was used, only add the tool call itself to history as assistant's "response"
                # This prevents the model from seeing its own verbose output or redundant tool calls.
                history = history + [{'role': 'assistant', 'content': tool_match_obj.group(0)}]
            else:
                # If no tool was used, add the full streamed output to history
                history = history + [{'role': 'assistant', 'content': out}]

            if tool_res:
                history = history + [{'role': 'user', 'content': tool_res}]
                # If the model generated text *in addition* to a tool call (i.e., it tried to provide a final answer),
                # then terminate the inner loop to prevent it from re-searching immediately.
                # If 'out' was ONLY a tool command, the loop continues for the model to process the tool_res.
                if tool_match_obj and out.strip() != tool_match_obj.group(0).strip(): # Check if tool_match_obj exists before accessing group(0)
                    loop_active = False
                elif not tool_match_obj:
                    # If there was text output but no tool, then the loop can end
                    loop_active = False
            else:
                # If no tool was found or executed by run_ui_tool, then the loop can end
                dashboard(curr_model, config['temperature']); loop_active = False
            # --- End of modified logic ---

# ────────────────────────────────────────────────────────────
# ENTRY POINT — this runs when you launch with:  %run saturn.py
# ────────────────────────────────────────────────────────────

def main():
    print(f'[saturn-startup] Booting Saturn v{SATURN_VERSION} ...')

    # If this copy was just installed by the auto-updater, skip
    # re-checking immediately (prevents any relaunch loops).
    just_updated = os.environ.pop('SATURN_JUST_UPDATED', None)
    if just_updated:
        print('[saturn-startup] * Freshly updated — welcome to v' + SATURN_VERSION)
    elif check_for_updates():
        return   # a newer version installed itself and already ran

    # "%run saturn.py setup" forces the wizard even if settings exist
    force_setup = len(sys.argv) > 1 and sys.argv[1].lower() == 'setup'

    config = None if force_setup else load_config()
    api_key = None

    if config:
        api_key = resolve_api_key(config)
        if api_key and _validate_key(api_key):
            print('[saturn-startup] * Loaded saved settings from ' + CONFIG_PATH)
        else:
            print('[saturn-startup] ! Saved key is missing or invalid — opening Setup Wizard.')
            config = None

    if not config:
        config, api_key = run_setup_wizard()

    print('[saturn-startup] * All systems go\n')
    time.sleep(0.5)
    try:
        start_saturn_console(api_key, config)
    except KeyboardInterrupt:
        print('\nDisconnected.')

if __name__ == '__main__':
    main()
