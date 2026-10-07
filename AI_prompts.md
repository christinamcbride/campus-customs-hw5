# AI Prompts — Campus Customs Multi-Agent Operations (MGT 409, Homework 5)

This file is the record of what I typed to my vibe coder while building this assignment.

There is one section per problem. Each section holds the problem number and title, at
least one prompt in my own words, and any follow-up prompts I needed — each follow-up
with one sentence on what was missing after the prompt before it.

Prompts are quoted word for word, exactly as I typed them, including typos and informal
phrasing. Sections are added as each problem is worked.

---

## Problem 1: Vibe Coder Prompts

### Kickoff prompt — describing the assignment

```
now we will work on homework 5 in the hw5 folder in the MGT409 folder on my desktop. we will build campus customs multi-agent operations
scenario:
campus customs multi-agent operations is the agentic team that runs the shop. open tickets land on a board—customer orders, rent, unpaid bills, discount requests, and whatever else the shop has to handle.
you will build three pieces that communicate with each other:

* an mcp server
* a fastapi backend with a multi-agent team
* a react dashboard so a human can watch the agents work and approve requests

your agent team has full connectivity. any agent may delegate tasks to any other agent for help.
in this assignment, you will build these agents:

* boss — reads each ticket, decides who should work on it, and makes final decisions
* inventory — checks stock by sku and size, spots shortfalls, and figures out which vendor can restock
* accounting — monitors cash and invoices, checks margins, and prepares payments or purchase orders for human approval
* facilities — handles the shop-space side, including leases and rent
* customer service — drafts messages for customers there is a data folder in the hw5 folder. this is the original shop database. the tables include:
   * `desk`
   * `tickets`
   * `inventory`
   * `pricing`
   * `vendors`
   * `leases`
   * `cash_accounts`
   * `payments`
   * `invoices`
your tools will update the database as tickets are resolved. make a copy of the database called `data/campus_customs_new.db` and point your mcp server and backend to that working copy.
keep `campus_customs.db` untouched so you can reset the database whenever you want to restart resolving the tickets.
rules of the shop
   * the field `desk.date_today` represents "today" for the shop. use this date to determine what is overdue.
   * vendor lead times come from the `vendors` table.
   * a vendor will not ship new product while they still have an open, unpaid invoice.
   * human approval is required for all payments. points will be deducted if this is not done. if a payment is made, update the relevant table.
   * if there is not enough cash, the payment tool must refuse the payment. negative balances are not allowed.
   * cash only goes out in this homework. revenue is not modeled, so no money comes in.
   * before a full run to resolve the tickets, reset the database to the original values.
   * do not email customers or call real vendors. drafts should stay on the board.
use your `PORTKEY_API_KEY` for ai calls. for this assignment, use only `gpt-6-luna` through portkey for every agent. multi-agent chats use tokens quickly. points will be deducted if any other model appears in your code or runs.
work on one problem at a time with your vibe coder. type each problem in your own words. do not paste the page url or screenshot the problems to finish everything. the final submission will be a public github repository. the last problem shows the required file tree. there will be 11 problems. lmk when ur ready for problem 1. this is a new assignment too so don't start recording prompts yet
```

### Prompt 1

```
problem 1: vibe coder prompts

create `AI_prompts.md` at the beginning of the assignment and keep it updated as i work. this file should be a record of what i typed.

put one section in `AI_prompts.md` for each problem. each section must include:

* the problem number and title
* at least one prompt you typed, written in your own words as much as possible
* one follow-up prompt if you needed one, along with one sentence explaining what was missing after the first prompt
```

---

## Problem 2: Study the Campus Customs Database

### Prompt 1

```
problem 2: study the campus customs database

open `data/campus_customs.db` and look through every table and its fields. copy the original database to `data/campus_customs_new.db`. later problems will update this working copy. study the three open tickets so we understand how they connect to the other tables.

start `output/harness.md`.
for each table, list its fields and write one short sentence explaining why that table matters to the agents. we will continue expanding this harness file in later problems.
```

---

## Problem 3: Build the MCP Server

### Prompt 1

```
problem 3: build the mcp server
write an mcp server in `mcp_server/` using fastmcp. it should connect to `data/campus_customs_new.db`, but you do not need to connect or run it yet.
every agent in this homework will use the tools in this mcp server. you will add more tools later, but for now create three tools that will be needed for the tickets in the database.
keep the tool names clear. never invent data; only use information from the database.
in `output/harness.md`, list each of the three mcp tools. for every tool, include:

* which table it reads
* which ticket it helps unlock: 101, 102, or 103
* one sentence explaining why it is the right tool for that ticket

avoid vague descriptions such as "reads inventory." connect each tool to the specific ticket it supports. also add a short `mcp_server/readme.md` file explaining:

* what the mcp server is for
* which database file it uses
* which three tools it provides
```

---

## Problem 4: Connect and Test the MCP Server

### Prompt 1

````
problem 4: connect and test the mcp server
please connect the mcp server you created in `mcp_server/` to this project so claude code can call its tools.
first, inspect the existing project and determine how the local mcp server should be configured for claude code. create or update `.mcp.json` at the project root, or use the appropriate local mcp configuration if claude code requires a different format.
make sure the mcp server uses the working database:

```
data/campus_customs_new.db
```

do not use or modify the original `data/campus_customs.db`.
after connecting the server, test all three mcp tools. save the test evidence in:

```
output/mcp_smoke.json
```

for each tool, record:

* the prompt or request used to test it
* the tool name
* the tool output
* confirmation that the output matches the data in `data/campus_customs_new.db`

use real values from the working database. do not invent or manually substitute tool results.
also update `AI_prompts.md` with the prompt i used for this problem and update any relevant documentation if the mcp configuration or tool usage needs to be explained.
````

---

## Problem 5: Build the Agent Team and Expand the MCP Tools

### Prompt 1

````
problem 5: build the agent team and expand the mcp tools
build the campus customs agent team using pydanticai. create these five agents:

* boss
* inventory
* accounting
* facilities
* customer service

give each agent its own detailed prompt, appropriate data models, and agent loop. the agents must be able to delegate work to one another with full connectivity.
store one prompt file per agent in:

```
backend/prompts/
```

put the shared data types in:

```
backend/models.py
```

put the agent implementation files under:

```
backend/
```

the exact file layout can vary as long as the five roles are clear.
use the `PORTKEY_API_KEY` environment variable and use only `gpt-6-luna` through portkey for every agent. do not use any other model.
write each prompt in your own words and include the shop rules that the agent needs. make the prompts detailed enough to explain each agent's responsibilities, scope, tools, delegation behavior, safety rules, and expected outputs.
add any tools the agents need to the existing mcp server so they can work on the open tickets.
all shop facts must come from the mcp server and the working database:

```
data/campus_customs_new.db
```

do not create a second shop-tools layer that bypasses mcp.
make sure the agents append activity to:

```
output/audit_trail.json
```

for every agent-loop step. record enough information to audit what happened later, including the time, agent, action or tool, relevant arguments or result summary, and stop reason when applicable. append to the file; do not erase it between runs.
update `output/harness.md` with:

* each agent and its responsibilities
* every mcp tool, including tools added in this problem
* the database table used by each tool
* a short safety section describing guardrails for customer data, payments, vendors, and other business actions
* limits that prevent excessive token use or runaway agent loops

update `mcp_server/readme.md` so its tool list matches the complete current set of tools.
inspect the existing implementation before changing it, preserve working code, run tests on the agent team and mcp tools, and report what you changed and what passed.
````

---

## Problem 6: Plan the Three Tickets

### Prompt 1

```
problem 6: Plan the Three Tickets. Create output/desk_tickets.html
The page must be openable by double-clicking and include one tab for each ticket:

* Ticket 101
* Ticket 102
* Ticket 103
* Cash
* Reflection

For each ticket tab, include:

* An `Expected` section describing what you expect the team to do.
* An empty `Actual` section with enough space to record what happens after the agents run.

In each ticket's `Expected` section, specify:

* Which person or agent the Boss should contact first, and why.
* Every agent delegation you expect, naming the specific agents involved.
* Which MCP tools you expect each agent to use.

Do not summarize the plan as "Boss calls everyone." List the expected delegation sequence in detail.
Leave the Cash and Reflection tabs blank or include a brief "Coming later" placeholder.
```

---

## Problem 7: Backend Routes

### Prompt 1

````
Problem 7: Backend Routes.
In `backend/main.py`, use FastAPI to add routes that support the frontend dashboard:

* Return the three tickets and whether each ticket is open or resolved.
* Accept a ticket ID and run the agent team for that ticket.
* Return recent agent events, including what each agent said and which tools they used, so the dashboard can refresh.
* Approve a payment or purchase after a human clicks an approval action. Agents may only prepare the payment; this route performs the actual cash change.
* Return the current checking balance from `cash_accounts`.
* Reset the database to its original values for a fresh run.

From the `backend/` directory, start the server with:

```
uvicorn main:app --reload --port 8000
```

The backend should be available at `http://localhost:8000` so the frontend dashboard can call the routes.
In `output/harness.md`, document every route using one line per route. For each route, include:

* The HTTP method and URL.
* A concise description of what the route does.
````

---

## Problem 8: Agent Dashboard

### Prompt 1

````
Now Problem 8: Agent Dashboard.
Build the frontend dashboard in `frontend/` using React, Vite, and TypeScript. The dashboard must call the backend routes from Problem 7.
At minimum, the dashboard must:

* List all three tickets.
* Allow a user to select one ticket and start its agent team.
* Show each agent's messages and activities while the ticket is being processed.
* Mark a ticket as resolved when its run finishes.
* Display a short summary of what each agent did for the ticket.
* Allow a human to approve a payment or purchase when approval is required.
* Display the checking balance and update it after an approved payment.

Configure the frontend to use the backend at:

```
http://localhost:8000
```

Configure the backend to allow requests from the Vite development server, usually:

```
http://localhost:5173
```

Start the frontend from the `frontend/` directory with:

```
npm run dev
```

Make the dashboard polished and inviting. Use a thoughtful layout and visual design that feels like a real operations desk. Clearly distinguish agent activity, resolved tickets, pending approvals, and cash information.
In `output/design.md`, document:

* The dashboard layout.
* How agent activity is visually differentiated.
* How resolved tickets are displayed.
* How cash and balance are displayed.
* The reasoning behind the design choices.
* The creative details that make the dashboard enjoyable and practical for human users.
````

---

## Problem 9: Resolve the Tickets

### Prompt 1

````
Problem 9: Resolve the Tickets.
Before testing the agents across all three tickets:

1. Reset the working database at `data/campus_customers_new.db`.
2. Record the starting checking balance after the reset.
3. Run tickets 101, 102, and 103 on the dashboard until all three are resolved.

Update `output/desk_tickets.html` from Problem 6:

* Keep each ticket's `Expected` section unchanged.
* Fill in the `Actual` section for tickets 101, 102, and 103.
* For each ticket, record which agents worked, what they delegated, and which tools they used.

Update the `Cash` tab in `output/desk_tickets.html` with:

* The starting checking balance after the reset.
* For each ticket, how the cash changed when it was resolved and why, including the payment or purchase and dollar amount.
* The ending checking balance.
* Verify that the ending balance matches the `cash_accounts` table in the working database.

Create `output/resolved_tickets.json`. For each ticket, include:

* Ticket ID.
* Final status.
* A short outcome summary.
* What each agent contributed.
* Any human approvals.

Create `output/resolved_board.html`, a page that can be opened by double-clicking. It should show the React dashboard after each ticket has been resolved:

* Ticket 101.
* Ticket 102.
* Ticket 103.

Append the real agent runs to `output/audit_trail.json`.
Finish `output/harness.md` so it documents:

* The database tables.
* The MCP tools.
* All five agents.
* The backend API routes.
* The frontend dashboard.
* The safety rules.

Verify the cash calculations carefully. The final balance must match the working database.
````

### Follow-up 1 — the purchase order against the remaining cash

```
Reject it — don't commit money we don't have
```

*Why I had to answer this:* ticket 103's team queued a $264 purchase order when only
$160 was left in checking, and because a purchase order moves no cash at the moment it
is placed, no rule in the tools would have stopped it — the call was mine to make, and
it changed how the ticket resolved.

---

## Problem 10: Reflection

### Prompt 1

```
okay lets leave it, for Problem 10: Reflection.
Open `output/desk_tickets.html` and fill in the `Reflection` tab. This is my reflection, let me know if it sounds good "[full draft reflection pasted in — five sections with bracketed placeholders such as [describe the main outcome], [agent name], [tool names], [starting balance] and [ending balance], covering: evaluating the agents' performance, comparing Actual with Expected, what would be simpler with one agent, three new problems the team could solve, three it could not, and a conclusion]"
it should address all of the following:

1. Evaluate the agents' performance on each ticket and explain your reasoning.
2. For each ticket, compare the `Actual` results with the `Expected` plan you wrote earlier.
3. Explain what would have been simpler to handle with one agent and tools instead of the agent team, and why.
4. Describe three new problems Campus Customs might face that this agent team could solve with the tools you built.
5. Describe three new problems Campus Customs might face that this agent team could not solve with the tools you built. For each one, explain which additional tools and agents would be needed.

Ground every answer in specific evidence from the app, including agent activity, delegations, tools used, ticket outcomes, approvals, and cash changes. Avoid generic discussion that is not connected to Campus Customs or the three completed tickets.
```

*Note on this entry:* the prompt contained a long pasted draft of my own reflection. It is
summarised in brackets above rather than reproduced in full, because the finished version
of that text is the deliverable itself and sits in the Reflection tab of
`output/desk_tickets.html`.

---

## Problem 11: Submit to GitHub

### Prompt 1

````
Complete Problem 11: Submit to GitHub.
Push the project code to a public GitHub repository so graders can clone and run it. Submit the repository URL to Canvas and save the same URL in:

```
output/github_url.txt
```

Do not commit or push the real `.env` file. Include `.env.example` instead.
Include both database files under `data/`:

* `data/campus_customs.db`
* `data/campus_customs_new.db`

Use this project structure:

[the required file tree, from `hw5/` down through AI_prompts.md, requirements.txt,
.env.example, .gitignore, .mcp.json, README.md, data/, mcp_server/, frontend/,
backend/ with prompts/, and output/]

Make sure `README.md` explains how to:

* Copy the original database to the working database for a clean run.
* Start the MCP server.
* Start the FastAPI backend.
* Start the React frontend.
* Reset the database before running all three tickets.

Before submitting, verify that:

* The repository is public.
* A fresh clone contains all required files.
* The real `.env` file is absent.
* Both database files are present.
* The README setup instructions are complete.
* `output/github_url.txt` contains the correct public repository URL.
````

### Follow-up 1 — the repository layout

```
Repo root = the project
```

*Why I had to answer this:* the required tree starts with `hw5/`, but unlike HW4 the
prose never said to put everything in a folder with that name, so it was ambiguous
whether the repo should contain an `hw5/` directory or simply be it.

### Follow-up 2 — the repository name

```
campus-customs-hw5
```

*Why I had to answer this:* the repository had to be created by hand because the `gh`
CLI is not installed, so the name was mine to pick.

### Follow-up 3 — token permissions

```
for the token, do i need to enable any permissions?
```

*Why I had to ask:* GitHub rejects account passwords for git operations, and the
instructions I was given did not say which scope a personal access token needs.

### Follow-up 4 — the token page looked different

```
i don't see repo as a checkbox or access public repositories.
```

*Why I had to ask:* GitHub now defaults to fine-grained tokens, whose permission model
is nothing like the classic `repo` checkbox tree I had been pointed at.

### Follow-up 5 — opening a terminal

```
can u open the terminal for me
```

*Why I had to ask:* the push needed a credential only I could type, so the command had
to be started in a terminal I could see and enter the token into myself.

### Follow-up 6

```
i think it went through
```

*Why I had to say this:* the first push attempt failed with a 403 because git silently
reused the HW4 credential, so it was not obvious the second attempt had actually
succeeded until the clone was checked.
