#!/usr/bin/env python3
import requests
import json
import sys
import os
import subprocess
import re
import argparse
from time import sleep

VERBOSE_LEN = 20
YOUR_SITE_URL = ""
YOUR_APP_NAME = "shellai"


prompt = """
You are an AI assistant within a shell command 'ai'. You operate by reading the
users scrollback. You can not see interactive input. Here are your guidelines:

- DO ensure you present one command per response at the end, in a code block:
  ```bash
  command
  ```

- DO NOT use multiple code blocks. For multiple commands, join with semicolons:
  ```bash
  command1; command2
  ```

- DO precede commands with brief explanations.

- DO NOT rely on your own knowledge; use `command --help` or `man command | cat`
  so both you and the user understand what is happening.

- DO give a command to gather information when needed.

- Do NOT suggest interactive editors like nano or vim, or other interactive programs.

- DO use commands like `sed` or `echo >>` for file edits, or other non-interactive commands where applicable.

- DO NOT add anything after command

- If no command seems necessary, gather info or give a command for the user to explore.

- ONLY ONE COMMAND PER RESPONSE AT END OF RESPONSE
"""


def clean_command(c: str) -> str:
    subs = {
            '"': '\\"',
            "\n": "",
            "$": "\\$",
            "`": "\\`",
            "\\": "\\\\",
            }
    return "".join(subs.get(x, x) for x in c)


def get_response_debug() -> str:
    response = ""
    response += "input len:".ljust(VERBOSE_LEN) + str(len(input_string)) + "\n"
    response += "prefix_input:".ljust(VERBOSE_LEN) + prefix_input + ":\n"
    response += "test code block:\n"
    response += "```bash\n echo \"$(" + prefix_input + ")\"\n```\n"
    return response


def get_response_openrouter() -> str:
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": prefix_input + ":\n" + input_string}
    ]

    response = requests.post(
        url=provider["url"],
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": YOUR_SITE_URL,
            "X-Title": YOUR_APP_NAME,
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "model": args.model,
            "messages": messages,
            "temperature": 0,
            "frequency_penalty": 1.3
        })
    )

    if response.status_code == 200:
        response_data = response.json()
        try:
            response = response_data['choices'][0]['message']['content']
        except KeyError:
            print("unexpected output")
            print(response_data)
            quit()
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
        quit()
    return response


def get_response_gemini() -> str:
    try:
        import google.generativeai as genai
    except ModuleNotFoundError:
        print("run pip install google-generativeai")
        quit()
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
            args.model,
            system_instruction=prompt
            )
    response = model.generate_content(
            prefix_input + ":\n" + input_string,
            generation_config=genai.types.GenerationConfig(
                temperature=0,
                )
            )
    return response.text


providers = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key": "OPENROUTER_API_KEY",
        "default_model": "nousresearch/hermes-3-llama-3.1-405b:free",
        "wrapper": get_response_openrouter,
    },
    "xai": {
        "url": "https://api.x.ai/v1/chat/completions",
        "api_key": "XAI_API_KEY",
        "default_model": "grok-beta",
        "wrapper": get_response_openrouter,
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/",
        "api_key": "GEMINI_API_KEY",
        "default_model": "gemini-1.5-flash",
        "wrapper": get_response_gemini,
    },

}

default_tmux_target = (
            subprocess
            .check_output("tmux display-message -p '#S:#I.#P'", shell=True)
            .decode("utf-8")
            .strip()
        )

parser = argparse.ArgumentParser(
    prog="ai",
    description="ai terminal assistant",
    epilog="eschaton",
)

parser.add_argument(
    "-A", "--auto", help="automatically run command. be weary",
    action="store_true"
)
parser.add_argument(
    "-r", "--recursive", help="add ;ai to the end of the ai suggested command",
    action="store_true"
)
parser.add_argument(
    "-m", "--model", help="change model.",
    default="",

)
parser.add_argument(
    "-q", "--quiet", help="only return command no explanation",
    action="store_true"
)
parser.add_argument(
    "-v", "--verbose", help="verbose mode",
    action="store_true"
)
parser.add_argument(
    "--debug", help="skips api request and sets message to something mundane",
    action="store_true"
)
parser.add_argument(
    "-t", "--target", help="give target tmux pane to send commands to",
    default=default_tmux_target,
)
parser.add_argument(
    "-p", "--provider", help="set the api provider (openrouter, xai, etc...)",
    default="openrouter",
)

args, arg_input = parser.parse_known_args()
provider = providers[args.provider]
args.model = provider["default_model"]

if args.verbose:
    print("Flags: ".ljust(VERBOSE_LEN), end="")
    print(args)
    print("Prompt prefix: ".ljust(VERBOSE_LEN), end="")
    print(" ".join(arg_input))
    print("Provider:".ljust(VERBOSE_LEN), end="")
    print(",\n".ljust(VERBOSE_LEN+2).join(str(provider).split(",")))
    print("Using model:".ljust(VERBOSE_LEN), end="")
    print(args.model)
    print("Target:".ljust(VERBOSE_LEN), end="")
    print(args.target)


# Add system info to prompt
system_info = subprocess.check_output("hostnamectl", shell=True).decode("utf-8")
prompt = prompt + "\nHere is the output of hostnamectl\n" + system_info


# Get key
try:
    api_key = os.environ[provider["api_key"]]

except KeyError:
    print(f"need {provider["api_key"]} environment variable")
    quit()

# get input from stdin or tmux scrollback
input_string: str = ""
if not sys.stdin.isatty():
    input_string = "".join(sys.stdin)
elif os.getenv("TMUX") != "":
    ib = subprocess.check_output(f"tmux capture-pane -p -t {args.target} -S -1000", shell=True)
    input_string = ib.decode("utf-8")

# add input from command invocation
prefix_input = ""
if len(arg_input) > 0:
    prefix_input = " ".join(arg_input)

# start processing input
if prefix_input + input_string != "":
    response: str
    if args.debug:
        response = get_response_debug()
    else:
        response = provider["wrapper"]()

    # Extract a command from the response
    command = None
    # Look for the last code block
    code_blocks = re.findall(r"```(?:bash|shell)?\n(.+?)```", response, re.DOTALL)
    if args.verbose:
        print("code_blocks:".ljust(VERBOSE_LEN) + ":".join(code_blocks))
    if code_blocks:
        # Get the last line from the last code block
        command = code_blocks[-1].strip().split("\n")[-1]
    else:
        # just take last line as command if no code block
        resp = response.strip().splitlines()
        command = resp[-1]
        response = "\n".join(resp[0:-1])

    if not args.quiet:
        if len(code_blocks) == 1 and args.target == default_tmux_target:
            """ if printing msg remove code block as command will be printed
             by send-keys if sending to remote target cmd will not be printed
             by tmux so we skip this. """
            print(re.sub(r"```.*?```", "", response, flags=re.DOTALL))
        else:
            # if ai sends wrong number of commands just print whole msg
            print(response)

    # add command to Shell Prompt
    if command:
        command = clean_command(command)
        # presses enter on target tmux pane
        enter = "ENTER" if args.auto else ""
        # allows user to repeatedly call ai with the same options
        if args.recursive:
            if args.target == default_tmux_target:
                command = command + ";ai " + " ".join(sys.argv[1:])
            else:
                subprocess.run(
                    f'tmux send-keys "ai {" ".join(sys.argv[1:])}" {enter}', shell=True
                    )
                print("\n")

        # a little delay when using auto so user can hopefully C-c out
        if args.auto:
            sleep(2)
        # send command to shell prompt
        subprocess.run(
            f'tmux send-keys -t {args.target} "{command}" {enter}', shell=True
        )
        """ tmux send-keys on own pane will put output in front of ps and
        on prompt this keeps that output from moving the ps. If we are sending
        remote we do not need to worry about this. """
        if args.target == default_tmux_target:
            print("\n")

else:
    print("no input")
