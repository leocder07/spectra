# Spectra — Pre-Sprint Setup Checklist
# Complete ALL items before launching Agent Teams. Estimated time: 1-2 hours.

---

## 1. Environment Setup (15 min)

- [ ] Node.js ≥20 installed
- [ ] Claude Code CLI installed and authenticated
- [ ] tmux installed (for split-pane Agent Teams view)
- [ ] `ANTHROPIC_API_KEY` set in environment
- [ ] Extra usage enabled in Anthropic Console (for fast mode billing)
- [ ] Verify Claude Code version supports Agent Teams:
  ```bash
  claude --version
  ```

## 2. Agent Teams Configuration (10 min)

- [ ] Enable Agent Teams in settings:
  ```bash
  # Add to ~/.claude/settings.json
  {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": true,
    "fastMode": true
  }
  ```
- [ ] Or set environment variable:
  ```bash
  export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
  ```
- [ ] Start tmux session:
  ```bash
  tmux new -s spectra
  ```
- [ ] Test Agent Teams works (spawn a quick test team, then shut down):
  ```
  Create a test team with 1 teammate. Have them say hello. Then shut down.
  ```

## 3. Project Initialization (20 min)

- [ ] Create project directory:
  ```bash
  mkdir spectra && cd spectra
  git init
  ```

- [ ] Copy CLAUDE.md to project root:
  ```bash
  cp /path/to/CLAUDE.md ./CLAUDE.md
  ```

- [ ] Initialize package.json:
  ```bash
  npm init -y
  ```

- [ ] Install core dependencies:
  ```bash
  npm install @anthropic-ai/sdk commander chalk ora simple-git tiktoken handlebars zod boxen cli-table3
  ```

- [ ] Install dev dependencies:
  ```bash
  npm install -D typescript vitest @biomejs/biome @types/node tsx
  ```

- [ ] Create tsconfig.json:
  ```json
  {
    "compilerOptions": {
      "target": "ES2022",
      "module": "NodeNext",
      "moduleResolution": "NodeNext",
      "lib": ["ES2022"],
      "outDir": "dist",
      "rootDir": "src",
      "strict": true,
      "esModuleInterop": true,
      "skipLibCheck": true,
      "forceConsistentCasingInFileNames": true,
      "resolveJsonModule": true,
      "declaration": true,
      "declarationMap": true,
      "sourceMap": true,
      "paths": {
        "@entities/*": ["./src/entities/*"],
        "@use-cases/*": ["./src/use-cases/*"],
        "@adapters/*": ["./src/adapters/*"],
        "@infrastructure/*": ["./src/infrastructure/*"]
      }
    },
    "include": ["src/**/*"],
    "exclude": ["node_modules", "dist", "tests"]
  }
  ```

- [ ] Create directory structure:
  ```bash
  mkdir -p src/entities src/use-cases src/adapters src/infrastructure/agents
  mkdir -p templates tests/entities tests/use-cases tests/integration tests/e2e
  mkdir -p golden-files
  ```

- [ ] Add bin entry to package.json:
  ```json
  {
    "bin": {
      "spectra": "./dist/infrastructure/main.js"
    },
    "type": "module"
  }
  ```

## 4. Skills Installation (15 min)

- [ ] Verify existing skills:
  ```bash
  ls /mnt/skills/user/
  # Should see: uncle-bob-master, cto-delegation, etc.
  ```

- [ ] Install Spectra-specific skills (if created from skill prompts):
  - spectra-architect
  - spectra-agent-orchestrator
  - spectra-brand-voice

- [ ] Verify skills load in Claude Code:
  ```
  What skills do you have available?
  ```

## 5. Test Repos Preparation (10 min)

- [ ] Identify 5 test repos (public GitHub URLs):
  1. express-starter (~500 LOC, JavaScript)
  2. react-dashboard (~5K LOC, TypeScript)
  3. fastapi-ml (~3K LOC, Python)
  4. nestjs-ecommerce (~15K LOC, TypeScript)
  5. django-saas (~20K LOC, Python)

- [ ] Verify each can be cloned:
  ```bash
  git clone --depth 1 <url> /tmp/test-repo && rm -rf /tmp/test-repo
  ```

## 6. Budget Tracking Setup (5 min)

- [ ] Note starting credit balance: $______
- [ ] Set budget alerts in Anthropic Console (if available)
- [ ] Create budget tracking note:
  ```
  Hour 0:  Starting balance: $5,500
  Hour 12: Target spend: <$800
  Hour 24: Target spend: <$1,600
  Hour 36: Target spend: <$2,500
  Hour 48: Target spend: <$3,500
  Buffer remaining: ~$2,000
  ```

## 7. Fast Mode Strategy (5 min)

- [ ] Fast mode ON for:
  - architect-1 (critical path, Hours 2-14)
  - pipeline-1 (core engine, Hours 10-32)

- [ ] Fast mode OFF (use standard Sonnet) for:
  - interface-1 (CLI/templates, not latency-sensitive)
  - qa-1 (tests, not latency-sensitive)

- [ ] Remember: `/fast` toggles fast mode per session
- [ ] Fast mode 50% discount ends Feb 16 — sprint should be within discount window

## 8. Demo Preparation (5 min)

- [ ] Identify hackathon judges' public repos (if known)
- [ ] Prepare 3 backup demo repos (well-known, interesting output)
- [ ] Test screen recording tool works
- [ ] Prepare backup video recording setup

---

## Launch Sequence

When all items above are checked:

1. Start tmux: `tmux new -s spectra`
2. Navigate to project: `cd spectra`
3. Launch Claude Code: `claude`
4. Enable fast mode: `/fast`
5. Paste the Agent Teams launch prompt (from agent-teams-launch-prompt.md)
6. Monitor teammates in split panes
7. Start the clock. 48 hours begins NOW.

---

## Emergency Contacts

- Anthropic API Status: https://status.anthropic.com
- Claude Code Issues: https://github.com/anthropics/claude-code/issues
- Agent Teams Docs: https://code.claude.com/docs/en/agent-teams
- Fast Mode Docs: https://code.claude.com/docs/en/fast-mode
