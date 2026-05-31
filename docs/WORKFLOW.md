# Dev & Deployment Workflow

No more hand-copying files to the VM. Code flows through GitHub.

```
  [Local Windows, no GPU]                    [GCP VM, Ubuntu, L4 GPU]
  Claude writes code  ──commit/push──►  GitHub  ──git pull──►  run & test here
        ▲                                                          │
        └─────────────── you report results back ◄────────────────┘
```

- **Local machine** = authoring only (no GPU). I write code; you commit & push.
- **VM** = the only place anything GPU runs. You pull and run there.
- **Why `git pull` and not GitHub Actions auto-deploy?** The GPU VM is powered off most of the
  time to save budget, so a push-triggered CI runner can't reach it. A pull on the VM is the
  pragmatic, reliable choice for now. (A self-hosted runner is a Phase 7 option once sessions
  are routine — see ROADMAP.)

---

## One-time: create the GitHub remote (run LOCALLY, Windows)

You run all git commands. Pick ONE option.

**Option A — GitHub CLI (if you have `gh`):**
```powershell
gh repo create ai-video-generation-pipeline --private --source . --remote origin --push
```

**Option B — Manual:** create an empty **private** repo named `ai-video-generation-pipeline` on
github.com (no README/license), then:
```powershell
git remote add origin git@github.com:<your-username>/ai-video-generation-pipeline.git
git push -u origin main
```
(Use the `https://github.com/...git` URL instead if you authenticate with a token over HTTPS.)

---

## One-time: clone onto the VM (run ON THE VM)

**Recommended location:** your home directory (no sudo, on the 100 GB disk).

```bash
# Authenticate the VM to GitHub for a PRIVATE repo. SSH key is cleanest:
ssh-keygen -t ed25519 -C "gcp-l4-vm" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
#   -> add this public key at https://github.com/settings/keys (or as a repo Deploy Key)

cd ~
git clone git@github.com:<your-username>/ai-video-generation-pipeline.git
cd ai-video-generation-pipeline
```

If you'd been running scripts from a hand-made copy elsewhere on the VM, delete it and use this
clone as the single source of truth. (Your downloaded model weights live in `~/.cache/huggingface`
and are NOT affected by re-cloning — no re-download.)

Then do the Phase 1 environment setup once: see [`SETUP.md`](SETUP.md).

---

## The everyday loop

1. I edit code locally and give you a commit message.
2. You: `git add . ; git commit ; git push` (you verify/approve the message).
3. On the VM: `bash scripts/dev_update.sh`  (pulls + syncs deps, leaves torch alone).
4. On the VM: `.venv/bin/python scripts/<whatever>.py`
5. You paste the output back; I react.

> Reminder: always run Python via `.venv/bin/python` on the VM. The scripts self-check and refuse
> to run outside the venv, so you can't accidentally hit system Python.
