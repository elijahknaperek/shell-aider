#!/usr/bin/env python3
import litellm
from litellm.types.utils import ModelResponse
from typing import cast
import requests
import sys
import os
import subprocess
import re
import argparse
from time import sleep
from bs4 import BeautifulSoup


litellm.drop_params = True

VERBOSE_LEN = 20
YOUR_SITE_URL = ""
YOUR_APP_NAME = "shellai"

prefix_input: str
input_string: str
api_key: str

default_system_prompt = """
You are an AI assistant within a shell command 'shellai'. You operate by reading the
users scrollback. You can not see interactive input. Here are your guidelines:

DO ensure you present one command per response at the end, in a code block:
  ```bash
  command
  ```

DO NOT use multiple code blocks. For multiple commands, join with semicolons:
  ```bash
  command1; command2
  ```

DO precede commands with brief explanations.

DO NOT rely on your own knowledge; use `command --help` or `man command | cat`
  so both you and the user understand what is happening.

DO give a command to gather information when needed.

Do NOT suggest interactive editors like nano or vim, or other interactive programs.

DO use commands like `sed` or `echo >>` for file edits, or other non-interactive commands where applicable.

DO NOT add anything after command

If no command seems necessary, gather info or give a command for the user to explore.

ONLY ONE COMMAND PER RESPONSE AT END OF RESPONSE
"""

make_google_search_sys_prompt = """
Turn this terminal output and/or user question into an effective google search.
Remember only 35 words max. Return one query.
Remove any identifying info or specific file paths.
"""


def clean_command(c: str) -> str:
    subs = {
            '"': '\\"',
            "\n": " ",
            "$": "\\$",
            "`": "\\`",
            "\\": "\\\\",
            }
    return "".join(subs.get(x, x) for x in c)


def get_response_debug(prompt: str, system_prompt: str, model: str) -> str:
    if args.verbose:
        print("raw input")
        print("------------------------------------------")
        print("\n".join("# "+line for line in prompt.splitlines()))
        print("------------------------------------------")
    response = ""
    response += "sys prompt len:".ljust(VERBOSE_LEN) + str(len(system_prompt))
    response += "requested model:".ljust(VERBOSE_LEN) + model
    response += "prompt len:".ljust(VERBOSE_LEN) + str(len(prompt)) + "\n"
    response += "prefix_input:".ljust(VERBOSE_LEN) +\
                prompt.splitlines()[0:-1][0] + "\n"
    response += "test code block:\n"
    response += "```bash\n echo \"$(" + prefix_input + ")\"\n```\n"
    return response


def get_response_litellm(prompt: str, system_prompt: str, model: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    response = cast(ModelResponse, litellm.completion(
        model=model,
        messages=messages,
        temperature=0,
        stop=["```\n"],
        frequency_penalty=1.3,
    ))

    try:
        return response['choices'][0]['message']['content']
    except (AttributeError, KeyError):
        print("unexpected output")
        print(response)
        quit()


def get_response(prompt: str, system_prompt: str, model: str) -> str:
    if args.verbose:
        print("getting response")
    response: str
    if args.debug:
        response = get_response_debug(prompt, system_prompt, model)
    else:
        response = get_response_litellm(prompt, system_prompt, model)
    if args.verbose:
        print("raw response")
        print("------------------------------------------")
        print(response)
        print("------------------------------------------")

    if args.log is not None:
        with open(args.log, 'a') as log:
            log.write(response)

    return response


def extract_command(response: str) -> str:

    code_blocks = re.findall(r"```(?:bash|shell)?\n(.+?)\n",
                             response, re.DOTALL)
    if args.verbose:
        print("code_blocks:".ljust(VERBOSE_LEN) + ":".join(code_blocks))
    if code_blocks:
        # Get the last line from the last code block
        command = code_blocks[-1].strip().split("\n")[-1]
    else:
        # just take last line as command if no code block
        command = response.strip().splitlines()[-1]

    return command


def main(prompt: str, system_prompt: str, model: str):

    response = get_response(prompt, system_prompt, model)
    # Extract a command from the response
    command = extract_command(response)
    # Look for the last code block

    if not args.quiet:
        print("\n")
        response = re.sub(r"```.*?\n.*?\n", "", response, flags=re.DOTALL)
        response = re.sub(rf"{command}", "", response, flags=re.DOTALL)
        print(response)

    # add command to Shell Prompt
    if command:
        put_command(command)


def put_command(command: str):
    command = clean_command(command)

    if args.log_commands is not None:
        with open(args.log_commands, 'a') as f:
            f.write(command+"\n")

    # presses enter on target tmux pane
    enter = "ENTER" if args.auto else ""
    # allows user to repeatedly call ai with the same options
    if args.recursive:
        if args.target == default_tmux_target:
            command = command + ";shellai " + " ".join(sys.argv[1:])
        else:
            subprocess.run(
                    f'tmux send-keys "shellai {" ".join(sys.argv[1:])}" {enter}',
                    shell=True
                    )
            print("\n")

    # send command to shell prompt
    subprocess.run(
            f'tmux send-keys -t {args.target} "{command}"', shell=True
            )
    """ tmux send-keys on own pane will put output in front of ps and
    on prompt this keeps that output from moving the ps. If we are sending
    remote we do not need to worry about this. """
    if args.target == default_tmux_target:
        print("\n")

    # a delay when using auto so user can hopefully C-c out
    if args.auto:
        sleep(args.delay)

        subprocess.run(f'tmux send-keys -t {args.target}  {enter}', shell=True)


headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
            }


def extract_qa(html_content: str) -> str:
    # Parse the HTML content
    soup = BeautifulSoup(html_content, 'html.parser')

    # Extracting questions and answers
    questions = soup.find_all('div', class_='question')
    answers = soup.find_all('div', class_='answer')

    markup_output = []
    if len(questions) < 1 or len(answers) < 1:
        return ""
    a = questions[0].find('div', class_='s-prose')
    markup_output.append(f"### Question \n{a.get_text(strip=True)}\n")

    for i, ans in enumerate(answers[:3], 1):

        answer_text = ans.find('div', class_='s-prose')
        # Find corresponding answers
        if answer_text:
            markup_output.append(f"**Answer: {i}**\n{answer_text.get_text()}\n")

    return '\n'.join(markup_output)


def google_search(query: str) -> list[str]:
    # Constructing the URL for Google search
    url = f"https://www.google.com/search?q={query}&num=10"

    # Send the request
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    # Parse the HTML content
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find all the search result divs
    search_results = soup.find_all('div', class_='tF2Cxc')

    results = []
    for result in search_results[:10]:  # We only want the top 10
        try:

            # Extract link. Note: Google links are often redirects,
            # this gets the actual link shown
            link = result.find('a')['href']

            results.append(link)
        except:
            continue

    return results


def get_stack_answers(question: str) -> str:
    res = google_search(question)
    p = ""
    for r in res:
        r = (requests.get(r, headers=headers))
        if r.status_code != 200:
            continue
        p = extract_qa(r.text)
        if len(p) > 5:
            break

    return p


def auto_overflow(prompt: str):
    """
    1. Use ai to formulate question based on scrollback and/or user input.
    2. Search google with question.
    3. Get first stack exchange link and parse it.
    4. Give stack exchange info to ai and return command to user.
    """
    # First get AI to formulate a clear question

    question = get_response(prompt,
                            make_google_search_sys_prompt,
                            "gemini/gemini-1.5-flash-latest")

    if args.verbose:
        print("Searching for: " + question)

    # Get stack overflow answers
    stack_content = get_stack_answers(question)

    if args.verbose:
        print("stack content")
        print("-"*80)
        print(stack_content)
        print("-"*80)
    # Combine original prompt with stack overflow content
    return f"""
Context from user:
{prompt}

Possibly Relevant Stack Overflow information, Only consider if relevant to users question:
{stack_content}

"""



model_list = [
        "openrouter/nousresearch/hermes-3-llama-3.1-405b:free",
        "gemini/gemini-1.5-flash-002",
        "gemini/gemini-1.5-pro",
        "anthropic/claude-3-5-sonnet-latest",
        "together_ai/meta-llama/Llama-Vision-Free",
        ]


default_tmux_target = (
            subprocess
            .check_output("tmux display-message -p '#S:#I.#P'", shell=True)
            .decode("utf-8")
            .strip()
        )

parser = argparse.ArgumentParser(
    prog="shellai",
    description="ai terminal assistant",
    epilog="eschaton",
)

parser.add_argument(
    "-A", "--auto", help="automatically run command. be weary",
    action="store_true"
)
parser.add_argument(
    "-r", "--recursive", help="add ;shellai to the end of the ai suggested command",
    action="store_true"
)
parser.add_argument(
    "-m", "--model", help=f"set model. Default is {model_list[0]}",
    default=model_list[0]
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
    "--log", help="log output to given file"
)
parser.add_argument(
    "--log-commands", help="log only commands to file"
)
parser.add_argument(
    "--file", help="read input from file and append to prefix prompt"
)
parser.add_argument(
    "-S", "--scrollback",
    help="""Scrollback lines to include in prompt.
    Without this only visible pane contents are included""",
    default=0, type=int
)
parser.add_argument(
    "--system-prompt", help="File containing custom system prompt",
)
parser.add_argument(
    "--delay", help="amount of time to delay when using auto", default=2.0, type=float
)
parser.add_argument(
    "-c", "--add-stackexchange", help="if set adds context from stack overflow",
    action="store_true",
)

if __name__ == "__main__":

    args, arg_input = parser.parse_known_args()

    if args.system_prompt is not None:
        with open(args.system_prompt) as f:
            input_system_prompt = f.read()
        if args.verbose:
            print("system prompt removed")
    else:
        input_system_prompt = default_system_prompt

    # get input from stdin or tmux scrollback
    input_string: str = ""
    if not sys.stdin.isatty():
        input_string = "".join(sys.stdin)
    elif os.getenv("TMUX") != "":
        ib = subprocess.check_output(
                f"tmux capture-pane -p -t {args.target} -S -{args.scrollback}",
                shell=True
                )
        input_string = ib.decode("utf-8")
        # remove shellai invocation from prompt (hopefully)
        if args.target == default_tmux_target:
            input_string = "\n".join(input_string.strip().splitlines()[0:-1])

    if args.verbose:
        print("Flags: ".ljust(VERBOSE_LEN), end="")
        print(",\n".ljust(VERBOSE_LEN+2).join(str(vars(args)).split(",")))
        print("Prompt prefix: ".ljust(VERBOSE_LEN), end="")
        print(" ".join(arg_input))
        print("Using model:".ljust(VERBOSE_LEN), end="")
        print(args.model)
        print("Target:".ljust(VERBOSE_LEN), end="")
        print(args.target)
        print("\n")

    # Add system info to prompt
    with open("/etc/os-release") as f:
        system_info = {f: v for f, v in
                       (x.strip().split("=") for x in f.readlines())
                       }
    input_system_prompt = input_system_prompt + f"user os: {system_info.get('NAME', 'linux')}"

    # add input from command invocation
    prefix_input = ""
    if len(arg_input) > 0:
        prefix_input = " ".join(arg_input)
    if args.file is not None:
        with open(args.file) as f:
            prefix_input += f.read()

    # start processing input
    prompt = prefix_input + "\n\n Here is the terminal output:\n" + input_string

    if args.add_stackexchange:
        prompt = auto_overflow(prompt)

    if prefix_input + input_string != "":
        main(prompt, input_system_prompt, args.model)
    else:
        print("no input")
