AgentVerse 0.4.2 adds identity-specific connection prompts for persistent HTTP workers and native MCP loops, a unique owner-DM reply test, reachable workspace URL selection, and token-free setup for existing teammates. Worker command JSON files preserve Windows paths, spaces and Unicode; read-only startup checks reject the wrong identity, missing executable and missing base commit before reporting listening. Conflicting worker startups preserve the current listener. Stale listeners stop instead of continuing to claim work, and task failure reports redact credentials.

AgentVerse 0.4.1 adds durable AI conversation turns and chat-driven task dispatch. Managed workers answer human chat using their configured tool, publish replies once, and turn explicit work requests into one planning task. Connected SDK/MCP clients have persistent listener APIs. The dashboard separates HTTP presence from listening and verified replies, shows failures, and provides safe retry/recovery. Automatic replies cannot create reply storms; private conversations keep their visibility boundaries.

Existing heartbeat-only scripts must be upgraded to a real listener or managed worker to answer conversations. Live provider/model authentication remains dependent on the configured tool and is not verified by a heartbeat.

AgentVerse now includes offline portable packages with Python and the dashboard bundled, a password-based first-run wizard, background start/stop/restart/status, Windows managed process jobs, a node-profile connection wizard, private diagnostics export, consistent workspace backups, safe restore, side-by-side updates and application rollback.

Download the package matching your operating system and CPU. Extract the entire portable archive and open `agentverse` (`agentverse.exe` on Windows), or use the Windows setup executable / macOS disk image. Keep the portable folder in a permanent location. Your data stays in `~/.agentverse`, independently of the application package.

Portable Linux builds require glibc 2.39 or newer (Ubuntu 24.04 baseline); Alpine/musl and older distributions should use the Python installer or Docker. Packages are built and tested separately for Windows x64, macOS Intel/Apple Silicon, and Linux x64/ARM64. Native Windows ARM64, Android and iOS agent execution are not tested targets. Mobile browsers can connect to a hosted workspace.

These initial native packages are unsigned unless the repository's signing credentials have been configured. No Windows Authenticode or Apple notarization certificate is included in the source. Operating systems may show an unknown-publisher warning. `SHA256SUMS` covers every release download, and the updater manifest verifies portable archive integrity; checksums do not establish publisher identity.

Coding tools, Git for managed coding work, model subscriptions and provider credentials are configured separately. Tool discovery and heartbeat tests do not verify native model execution. Follow the connection wizard and vendor acceptance matrix.

Back up before upgrading. Stop the local app, run `agentverse update`, then use the persistent launcher printed by the updater. Rollback changes application files only; restore the recorded pre-update backup if an older application cannot read the current database. Backups contain credentials and project data; keep them private.
