import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Sequence,
} from "remotion";

const C = {
  bg: "#0d1117",
  panel: "#161b22",
  border: "#30363d",
  text: "#c9d1d9",
  white: "#e6edf3",
  green: "#3fb950",
  blue: "#58a6ff",
  yellow: "#d29922",
  red: "#f85149",
  cyan: "#39c5cf",
  magenta: "#bc8cff",
  orange: "#f0883e",
  dimmed: "#484f58",
  purple: "#d2a8ff",
};

// ─── Primitives ───

const TypedText = ({ text, startFrame, speed = 2, color = C.text, bold = false }) => {
  const frame = useCurrentFrame();
  const elapsed = frame - startFrame;
  if (elapsed < 0) return null;
  const chars = Math.min(Math.floor(elapsed * speed), text.length);
  return (
    <span style={{ color, fontWeight: bold ? 700 : 400 }}>
      {text.slice(0, chars)}
      {chars < text.length && (
        <span style={{ opacity: Math.sin(frame * 0.3) > 0 ? 1 : 0, color: C.green }}>▊</span>
      )}
    </span>
  );
};

const Line = ({ children, at }) => {
  const frame = useCurrentFrame();
  if (frame < at) return null;
  const opacity = interpolate(frame - at, [0, 4], [0, 1], { extrapolateRight: "clamp" });
  return <div style={{ minHeight: "1.5em", opacity }}>{children}</div>;
};

const Badge = ({ label, color, icon }) => (
  <span
    style={{
      background: `${color}18`,
      color,
      border: `1px solid ${color}50`,
      padding: "2px 10px",
      borderRadius: "4px",
      fontSize: "13px",
      fontWeight: 700,
      marginRight: "10px",
      letterSpacing: "0.5px",
    }}
  >
    {icon && <span style={{ marginRight: "5px" }}>{icon}</span>}
    {label}
  </span>
);

const Spinner = ({ startFrame, duration = 60 }) => {
  const frame = useCurrentFrame();
  const elapsed = frame - startFrame;
  if (elapsed < 0 || elapsed > duration) return null;
  const chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
  return <span style={{ color: C.cyan }}>{chars[Math.floor(elapsed / 3) % chars.length]}</span>;
};

const ProgressBar = ({ startFrame, duration = 40, width = 30 }) => {
  const frame = useCurrentFrame();
  const elapsed = frame - startFrame;
  if (elapsed < 0) return null;
  const progress = Math.min(elapsed / duration, 1);
  const filled = Math.floor(progress * width);
  return (
    <span>
      <span style={{ color: C.green }}>{"█".repeat(filled)}</span>
      <span style={{ color: C.dimmed }}>{"░".repeat(width - filled)}</span>
      <span style={{ color: C.text }}> {Math.floor(progress * 100)}%</span>
    </span>
  );
};

// ─── Bar Chart Component ───

const BarChart = ({ startFrame, data }) => {
  const frame = useCurrentFrame();
  const elapsed = frame - startFrame;
  if (elapsed < 0) return null;

  const maxVal = Math.max(...data.map((d) => d.value));
  const barMaxWidth = 480;

  return (
    <div style={{ padding: "8px 0 0 20px" }}>
      {data.map((d, i) => {
        const delay = i * 6;
        const barProgress = interpolate(elapsed - delay, [0, 20], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const barWidth = (d.value / maxVal) * barMaxWidth * barProgress;
        return (
          <div
            key={d.label}
            style={{
              display: "flex",
              alignItems: "center",
              marginBottom: "6px",
              opacity: elapsed > delay ? 1 : 0,
            }}
          >
            <span
              style={{
                color: C.dimmed,
                width: "130px",
                textAlign: "right",
                marginRight: "12px",
                fontSize: "14px",
              }}
            >
              {d.label}
            </span>
            <div
              style={{
                height: "22px",
                width: `${barWidth}px`,
                background: `linear-gradient(90deg, ${d.color}cc, ${d.color})`,
                borderRadius: "3px",
                transition: "width 0.1s",
              }}
            />
            <span
              style={{
                color: C.white,
                marginLeft: "10px",
                fontSize: "14px",
                fontWeight: 600,
                opacity: barProgress > 0.8 ? 1 : 0,
              }}
            >
              {d.pct}
            </span>
            {d.note && barProgress > 0.9 && (
              <span style={{ color: d.noteColor || C.dimmed, marginLeft: "10px", fontSize: "12px" }}>
                {d.note}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
};

// ─── Parallel Agent Panel ───

const AgentPanel = ({ label, number, color, status, statusColor, detail, at }) => {
  const frame = useCurrentFrame();
  if (frame < at) return null;
  const slideIn = interpolate(frame - at, [0, 10], [30, 0], { extrapolateRight: "clamp" });
  const opacity = interpolate(frame - at, [0, 8], [0, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        background: C.panel,
        border: `1px solid ${color}40`,
        borderRadius: "8px",
        padding: "12px 16px",
        width: "270px",
        opacity,
        transform: `translateY(${slideIn}px)`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", marginBottom: "6px" }}>
        <span style={{ color, fontSize: "12px", fontWeight: 700, letterSpacing: "0.5px" }}>
          GRAD STUDENT {number}
        </span>
      </div>
      <div style={{ color: C.text, fontSize: "13px", marginBottom: "4px" }}>{label}</div>
      {detail && <div style={{ color: C.dimmed, fontSize: "11px", marginBottom: "6px" }}>{detail}</div>}
      {status && (
        <div
          style={{
            display: "inline-block",
            background: `${statusColor}18`,
            color: statusColor,
            border: `1px solid ${statusColor}50`,
            padding: "1px 8px",
            borderRadius: "3px",
            fontSize: "11px",
            fontWeight: 600,
          }}
        >
          {status}
        </div>
      )}
    </div>
  );
};

// ─── Main Component ───

export const DecisionLabDemo = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [1160, 1200], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  // Scroll the terminal content as the session progresses
  const scrollY = interpolate(
    frame,
    [0, 90, 180, 350, 480, 600, 720, 860, 980, 1060],
    [0, 0, -80, -300, -560, -780, -1020, -1350, -1680, -1900],
    { extrapolateRight: "clamp" }
  );

  // Show the chart overlay in the final section
  const showChart = frame >= 920;
  const chartOpacity = interpolate(frame, [920, 940], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: C.bg,
        fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', monospace",
        fontSize: "15px",
        lineHeight: "1.55",
        opacity: fadeIn * fadeOut,
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* ─── Terminal Chrome ─── */}
      <div
        style={{
          height: "40px",
          background: C.panel,
          display: "flex",
          alignItems: "center",
          padding: "0 18px",
          gap: "8px",
          borderBottom: `1px solid ${C.border}`,
          position: "relative",
          zIndex: 10,
        }}
      >
        <div style={{ width: 12, height: 12, borderRadius: "50%", background: C.red }} />
        <div style={{ width: 12, height: 12, borderRadius: "50%", background: C.yellow }} />
        <div style={{ width: 12, height: 12, borderRadius: "50%", background: C.green }} />
        <span style={{ color: C.dimmed, marginLeft: "20px", fontSize: "13px" }}>
          decision-lab — ~/analysis
        </span>
        <span style={{ color: C.dimmed, fontSize: "13px", marginLeft: "auto" }}>
          dlab v0.1
        </span>
      </div>

      {/* ─── Scrolling Terminal Content ─── */}
      <div
        style={{
          padding: "24px 36px",
          transform: `translateY(${scrollY}px)`,
        }}
      >
        {/* ═══ SCENE 1: User types the question (0-80) ═══ */}
        <Line at={5}>
          <span style={{ color: C.green }}>❯ </span>
          <span style={{ color: C.cyan }}>dlab</span>
          <span style={{ color: C.dimmed }}> --dpack </span>
          <span style={{ color: C.orange }}>mmm</span>
          <span style={{ color: C.dimmed }}> --data </span>
          <span style={{ color: C.text }}>./ad-spend.csv</span>
        </Line>

        <Line at={30}>
          <span style={{ color: C.dimmed }}>  prompt: </span>
          <TypedText
            text="We doubled Q4 ad spend but sales barely moved. What's working and what's wasted?"
            startFrame={30}
            speed={2.2}
            color={C.white}
          />
        </Line>

        {/* ═══ SCENE 2: Professor plans (80-170) ═══ */}
        <Line at={85}>
          <span>{""}</span>
        </Line>
        <Line at={90}>
          <Badge label="PROFESSOR" color={C.blue} icon="🎓" />
          <span style={{ color: C.white, fontWeight: 600 }}>Designing research agenda...</span>
        </Line>

        <Line at={110}>
          <span style={{ color: C.dimmed }}>  │</span>
        </Line>
        <Line at={115}>
          <span style={{ color: C.dimmed }}>  ├─ </span>
          <span style={{ color: C.text }}>Load & validate 2 years of weekly channel spend + revenue</span>
        </Line>
        <Line at={125}>
          <span style={{ color: C.dimmed }}>  ├─ </span>
          <span style={{ color: C.text }}>Fan out 3 grad students with different modeling strategies</span>
        </Line>
        <Line at={135}>
          <span style={{ color: C.dimmed }}>  ├─ </span>
          <span style={{ color: C.text }}>Each must pass convergence + posterior predictive checks</span>
        </Line>
        <Line at={145}>
          <span style={{ color: C.dimmed }}>  ├─ </span>
          <span style={{ color: C.text }}>Consolidate results — only trust where paths agree</span>
        </Line>
        <Line at={155}>
          <span style={{ color: C.dimmed }}>  └─ </span>
          <span style={{ color: C.yellow }}>If paths diverge: report "insufficient evidence"</span>
        </Line>

        {/* ═══ SCENE 3: Data prep (170-270) ═══ */}
        <Line at={175}>
          <span>{""}</span>
        </Line>
        <Line at={180}>
          <Badge label="DATA PREP" color={C.cyan} icon="📋" />
          <span style={{ color: C.text }}>Loading marketing data... </span>
          {frame >= 180 && frame < 210 && <Spinner startFrame={180} duration={30} />}
        </Line>

        <Line at={215}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>
            <span style={{ color: C.white, fontWeight: 600 }}>104 weeks</span> across{" "}
            <span style={{ color: C.white, fontWeight: 600 }}>6 channels</span>
            <span style={{ color: C.dimmed }}> — TV, Paid Search, Social, Display, Email, Affiliates</span>
          </span>
        </Line>

        <Line at={235}>
          <span>{""}</span>
        </Line>
        <Line at={240}>
          <Badge label="DATA PREP" color={C.cyan} icon="📋" />
          <span style={{ color: C.yellow }}>⚠ Anomaly detected</span>
        </Line>
        <Line at={250}>
          <span style={{ color: C.yellow }}>
            {"    "}Paid Search shows $0 for weeks 38-41 — unlikely during Q4 ramp
          </span>
        </Line>
        <Line at={262}>
          <span style={{ color: C.green }}>    ✓ </span>
          <span style={{ color: C.text }}>Imputed from adjacent weeks via rolling median</span>
        </Line>

        {/* ═══ SCENE 4: Parallel grad students fan out (270-480) ═══ */}
        <Line at={280}>
          <span>{""}</span>
        </Line>
        <Line at={285}>
          <Badge label="PROFESSOR" color={C.blue} icon="🎓" />
          <span style={{ color: C.white, fontWeight: 600 }}>
            Dispatching 3 grad students in parallel
          </span>
        </Line>

        {/* Three agent panels side by side */}
        <Line at={300}>
          <div style={{ display: "flex", gap: "16px", margin: "10px 0 10px 20px" }}>
            <AgentPanel
              number="1"
              label="Informative priors"
              detail="Hierarchical model + industry benchmarks"
              color={C.purple}
              status={frame >= 420 ? "✓ CONVERGED — R̂ 1.01" : frame >= 350 ? "Sampling..." : "Starting..."}
              statusColor={frame >= 420 ? C.green : C.cyan}
              at={305}
            />
            <AgentPanel
              number="2"
              label="Weakly informative priors"
              detail="Additive model + broad priors"
              color={C.orange}
              status={
                frame >= 520
                  ? "✓ CONVERGED (retry) — R̂ 1.02"
                  : frame >= 440
                  ? "↩ Revising..."
                  : frame >= 400
                  ? "✗ DIVERGENT — R̂ 2.4"
                  : frame >= 350
                  ? "Sampling..."
                  : "Starting..."
              }
              statusColor={
                frame >= 520 ? C.green : frame >= 440 ? C.yellow : frame >= 400 ? C.red : C.cyan
              }
              at={315}
            />
            <AgentPanel
              number="3"
              label="Flat priors + events"
              detail="Saturating model + holiday calendar"
              color={C.magenta}
              status={frame >= 430 ? "✓ CONVERGED — R̂ 1.01" : frame >= 350 ? "Sampling..." : "Starting..."}
              statusColor={frame >= 430 ? C.green : C.cyan}
              at={325}
            />
          </div>
        </Line>

        {/* Fitting progress */}
        <Line at={350}>
          <span style={{ color: C.dimmed }}>  </span>
          {frame >= 350 && <ProgressBar startFrame={350} duration={50} width={50} />}
        </Line>

        {/* Grad student 2 fails */}
        <Line at={410}>
          <span>{""}</span>
        </Line>
        <Line at={415}>
          <Badge label="GRAD STUDENT 2" color={C.orange} />
          <span style={{ color: C.red, fontWeight: 600 }}>✗ Posterior Predictive Check FAILED</span>
        </Line>
        <Line at={428}>
          <span style={{ color: C.red }}>
            {"    "}Model under-predicts holiday weeks by 22% — missing seasonal structure
          </span>
        </Line>

        {/* Professor sends back */}
        <Line at={448}>
          <span>{""}</span>
        </Line>
        <Line at={453}>
          <Badge label="PROFESSOR" color={C.blue} icon="🎓" />
          <span style={{ color: C.yellow, fontWeight: 600 }}>↩ Revision for Grad Student 2</span>
        </Line>
        <Line at={465}>
          <span style={{ color: C.yellow }}>
            {"    "}Add Black Friday + Christmas event dummies and re-fit
          </span>
        </Line>

        {/* Re-fit progress */}
        <Line at={485}>
          <Badge label="GRAD STUDENT 2" color={C.orange} />
          <span style={{ color: C.text }}>Re-fitting with holiday effects... </span>
          {frame >= 485 && frame < 515 && <Spinner startFrame={485} duration={30} />}
        </Line>

        <Line at={520}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>Converged on retry — R̂ 1.02, PPC passed</span>
        </Line>

        {/* ═══ SCENE 5: Dissertation Defense (540-700) ═══ */}
        <Line at={545}>
          <span>{""}</span>
        </Line>
        <Line at={550}>
          <div
            style={{
              background: `${C.green}10`,
              border: `1px solid ${C.green}40`,
              borderRadius: "8px",
              padding: "12px 18px",
              display: "inline-block",
            }}
          >
            <Badge label="DISSERTATION DEFENSE" color={C.green} icon="⚖" />
            <span style={{ color: C.white, fontWeight: 600 }}>
              Consolidating 3 analytical paths
            </span>
          </div>
        </Line>

        <Line at={575}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>
            All 3 grad students converged (1 after revision)
          </span>
        </Line>
        <Line at={590}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>
            Channel rankings agree across all 3 approaches
          </span>
        </Line>
        <Line at={605}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>
            Saturation curves consistent within credible intervals
          </span>
        </Line>

        <Line at={625}>
          <span>{""}</span>
        </Line>
        <Line at={630}>
          <Badge label="PROFESSOR" color={C.blue} icon="🎓" />
          <span style={{ color: C.white, fontWeight: 700 }}>
            Verdict: Strong consensus — recommendation is robust
          </span>
        </Line>

        {/* ═══ SCENE 6: Results + Channel Chart (650-920) ═══ */}
        <Line at={660}>
          <span>{""}</span>
        </Line>
        <Line at={665}>
          <span
            style={{
              color: C.white,
              fontWeight: 700,
              fontSize: "17px",
              borderBottom: `2px solid ${C.blue}`,
              paddingBottom: "4px",
            }}
          >
            Channel Contribution — Consensus Across All 3 Models
          </span>
        </Line>

        <Line at={680}>
          <BarChart
            startFrame={685}
            data={[
              { label: "Paid Search", value: 34, pct: "34%", color: C.green, note: "ROAS 4.2x ↑", noteColor: C.green },
              { label: "TV", value: 24, pct: "24%", color: C.cyan, note: "saturating ↓", noteColor: C.yellow },
              { label: "Social", value: 15, pct: "15%", color: C.magenta, note: "growing ↑", noteColor: C.green },
              { label: "Email", value: 13, pct: "13%", color: C.blue },
              { label: "Display", value: 9, pct: "9%", color: C.orange, note: "ROAS 0.8x ↓", noteColor: C.red },
              { label: "Affiliates", value: 5, pct: "5%", color: C.dimmed },
            ]}
          />
        </Line>

        {/* Key insight */}
        <Line at={810}>
          <span>{""}</span>
        </Line>
        <Line at={815}>
          <div
            style={{
              background: `${C.blue}10`,
              border: `1px solid ${C.blue}40`,
              borderRadius: "8px",
              padding: "14px 20px",
              maxWidth: "800px",
            }}
          >
            <div style={{ color: C.white, fontWeight: 700, marginBottom: "8px", fontSize: "16px" }}>
              Key Finding
            </div>
            <TypedText
              text="TV spend hit saturation — doubling the budget yielded only 8% incremental lift. Meanwhile Paid Search has 2.3x headroom before diminishing returns."
              startFrame={820}
              speed={1.8}
              color={C.text}
            />
          </div>
        </Line>

        <Line at={885}>
          <div
            style={{
              background: `${C.green}10`,
              border: `1px solid ${C.green}40`,
              borderRadius: "8px",
              padding: "14px 20px",
              maxWidth: "800px",
              marginTop: "8px",
            }}
          >
            <div style={{ color: C.green, fontWeight: 700, marginBottom: "8px", fontSize: "16px" }}>
              Recommendation
            </div>
            <TypedText
              text="Shift 30% of TV budget → Paid Search & Social. Estimated revenue impact: +19% (95% CI: +12% to +27%)."
              startFrame={890}
              speed={1.8}
              color={C.text}
            />
          </div>
        </Line>

        <Line at={960}>
          <span style={{ color: C.dimmed, fontSize: "13px" }}>
            {"    "}3 models • 3 convergent paths • 24,000 posterior samples • 6 channels decomposed
          </span>
        </Line>

        {/* Reports saved */}
        <Line at={990}>
          <span>{""}</span>
        </Line>
        <Line at={995}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>Report saved → </span>
          <span style={{ color: C.cyan }}>./analysis-001/report.html</span>
        </Line>
        <Line at={1005}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>Figures saved → </span>
          <span style={{ color: C.cyan }}>./analysis-001/figures/</span>
        </Line>
        <Line at={1015}>
          <span style={{ color: C.green }}>  ✓ </span>
          <span style={{ color: C.text }}>Session cost: </span>
          <span style={{ color: C.white, fontWeight: 600 }}>$2.34</span>
          <span style={{ color: C.dimmed }}> (4m 12s)</span>
        </Line>

        {/* Prompt returns */}
        <Line at={1040}>
          <span>{""}</span>
        </Line>
        <Line at={1045}>
          <span style={{ color: C.green }}>❯ </span>
          <span style={{ opacity: Math.sin(frame * 0.3) > 0 ? 1 : 0, color: C.green }}>▊</span>
        </Line>
      </div>

      {/* ─── Outro overlay ─── */}
      {frame >= 1080 && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: C.bg,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            opacity: interpolate(frame, [1080, 1110], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            zIndex: 20,
          }}
        >
          <div
            style={{
              fontSize: "52px",
              fontWeight: 800,
              color: C.white,
              letterSpacing: "-1px",
              marginBottom: "16px",
            }}
          >
            decision-lab
          </div>
          <div
            style={{
              fontSize: "20px",
              color: C.dimmed,
              marginBottom: "40px",
              fontStyle: "italic",
            }}
          >
            Science-grade rigor. Startup-grade speed.
          </div>
          <div style={{ fontSize: "16px", color: C.blue, letterSpacing: "2px" }}>
            AGENTIC DECISION SCIENCE
          </div>
          <div style={{ fontSize: "14px", color: C.dimmed, marginTop: "30px" }}>
            pip install dlab-cli
          </div>
          <div style={{ fontSize: "13px", color: C.dimmed, marginTop: "10px" }}>
            github.com/pymc-labs/decision-lab
          </div>
        </div>
      )}
    </div>
  );
};
