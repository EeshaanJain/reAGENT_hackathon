# Links

- Google Drive: [https://drive.google.com/drive/folders/1fsiPXOGGShZWvhF4Ga7Ou788maYAE0cv](https://drive.google.com/drive/folders/1fsiPXOGGShZWvhF4Ga7Ou788maYAE0cv)   
- Github: [https://github.com/EeshaanJain/reAGENT\_hackathon](https://github.com/EeshaanJain/reAGENT_hackathon)  
- Slides: [https://docs.google.com/presentation/d/13XIQRnqN55-Ss9GWZW8pkZxzTWERaCjkGrvCPaQ9e\_8/edit?slide=id.g3f721b1e4f5\_0\_20\#slide=id.g3f721b1e4f5\_0\_20](https://docs.google.com/presentation/d/13XIQRnqN55-Ss9GWZW8pkZxzTWERaCjkGrvCPaQ9e_8/edit?slide=id.g3f721b1e4f5_0_20#slide=id.g3f721b1e4f5_0_20)  
- OpenProblems: [https://github.com/openproblems-bio](https://github.com/openproblems-bio)  
- [https://scitra.org/](https://scitra.org/)   
- Project overview/directions  
- [https://docs.google.com/document/d/1tbkhSEwGvuMoToBS31hWh9xZGgKU\_gkg4uPO7AviheE/edit?tab=t.0](https://docs.google.com/document/d/1tbkhSEwGvuMoToBS31hWh9xZGgKU_gkg4uPO7AviheE/edit?tab=t.0)   
- Openproblems fork: [https://github.com/EeshaanJain/openproblems](https://github.com/EeshaanJain/openproblems)




# Literature agent

# Literature agent

* Aware of existing Open Problems benchmarks  
* Screens new literature every week  
* If a dataset / method / metric is relevant for existing benchmarks, it sends to a corresponding agent:  
  * Paper link and text  
    * Methods section  
    * Preprocessing / input assumptions  
  * Code link  
  * Description of what to do next (e.g. “Integrate this method to Open Problems chemical perturbation prediction benchmark”)  
* Literature search options:  
  * Paperclip – limitation: only updates the database once a month  
  * Paperbee  
* A way to evaluate – Philipp’s database: [https://github.com/EeshaanJain/reAGENT\_hackathon/blob/main/db/perturbation\_model\_papers.csv](https://github.com/EeshaanJain/reAGENT_hackathon/blob/main/db/perturbation_model_papers.csv) 

*   
*   
  \# Paperclip quick guide  
    
  This guide targets the installed CLI at \`/Users/jain/.local/bin/paperclip\`  
  (version 0.7.36). If that directory is on \`PATH\`, use \`paperclip\` as shown below;  
  otherwise replace it with the full binary path.  
    
  Official documentation: \<https://paperclip.gxl.ai/docs\>  
    
  \#\# 1\. Check setup  
    
  \`\`\`bash  
  paperclip \--version  
  paperclip config \--show  
  paperclip login                 *\# only if not signed in*  
  \`\`\`  
    
  Paperclip needs its remote service. If a command reports that the server is  
  unreachable, check the network/VPN and retry \`paperclip config \--show\`.  
    
  \#\# 2\. Search for papers  
    
  The installed CLI requires a source with \`-s\`. Useful sources are \`pmc\`,  
  \`biorxiv\`, \`medrxiv\`, \`arxiv\`, and \`abstracts\`; combine them with commas.  
    
  \`\`\`bash  
  *\# A focused full-text search*  
  paperclip search \-s pmc,biorxiv,medrxiv,arxiv \\  
   "diffusion models for protein design" \-n 10  
    
  *\# Machine-readable output*  
  paperclip search \-s pmc,biorxiv,medrxiv,arxiv \\  
   "diffusion models for protein design" \-n 20 \--json \> search-results.json  
  \`\`\`  
    
  The output includes paper IDs such as \`PMC1234567\`, \`bio\_abcd...\`, or  
  \`arxiv\_...\`, plus a saved result ID such as \`s\_4a2b61f6\`. Keep that result ID:  
    
  \`\`\`bash  
  paperclip results \--list  
  paperclip results s\_4a2b61f6  
  paperclip results s\_4a2b61f6 \--save search-results.csv  
  \`\`\`  
    
  \#\# 3\. Create and maintain a paper repo  
    
  A Paperclip repo is a persistent, git-like curated collection of paper  
  pointers and verified claims. It is not a local Git repository containing  
  PDFs.  
    
  \`\`\`bash  
  *\# Create it; this also makes it the active (sticky) repo*  
  paperclip repo init protein-diffusion \\  
   "ML methods for diffusion-based protein design"  
    
  *\# Search the public corpus (the search is recorded in the active repo)*  
  paperclip search \-s pmc,biorxiv,medrxiv,arxiv \\  
   "diffusion models for protein design" \-n 10  
    
  *\# Add selected hits, optionally with a claim and supporting line range*  
  paperclip repo add PMC1234567  
  paperclip repo add arxiv\_abcd1234 \\  
   "The method generates backbone structures with a diffusion model" \\  
   \--lines L210-L225  
    
  paperclip repo status  
  paperclip repo commit \-m "Add initial protein-diffusion methods"  
  \`\`\`  
    
  Useful repo operations:  
    
  \`\`\`bash  
  paperclip repo                         *\# list repos*  
  paperclip repo checkout protein-diffusion  
  paperclip \--repo protein-diffusion repo status  *\# one command, no sticky change*  
  paperclip \--repo-only search \-s pmc "inverse folding"  *\# search curated papers only*  
  paperclip repo history                 *\# command audit trail*  
  paperclip repo log                     *\# commits*  
  paperclip repo export bibtex \-o protein-diffusion.bib  
  paperclip repo export markdown \-o protein-diffusion.md  
  paperclip repo export csv \-o protein-diffusion.csv  
  paperclip repo checkout \-              *\# deactivate the sticky repo*  
  \`\`\`  
    
  To add all hits automatically, recent Paperclip versions also support search  
  flags such as \`--add\` and \`--commit\`; selecting papers manually is safer for a  
  small, high-quality review.  
    
  \#\# 4\. Read or dump a paper locally  
    
  Each paper is a virtual directory containing \`meta.json\`, line-numbered full  
  text in \`content.lines\`, sections, figures, and sometimes supplements.  
    
  \`\`\`bash  
  PAPER\_ID\=PMC1234567  
  paperclip tree /papers/$PAPER\_ID/  
  paperclip cat /papers/$PAPER\_ID/meta.json  
  paperclip head \-50 /papers/$PAPER\_ID/content.lines  
  paperclip grep \-i \-C 3 "github\\|code availability" \\  
   /papers/$PAPER\_ID/content.lines  
  \`\`\`  
    
  \`cat\` truncates large text by default. To dump the complete parsed paper,  
  first obtain its line count and then request the entire range:  
    
  \`\`\`bash  
  paperclip wc \-l /papers/$PAPER\_ID/content.lines  
  *\# Replace 847 below with the reported count.*  
  paperclip cat \--lines 1-847 /papers/$PAPER\_ID/content.lines \\  
   \> "${PAPER\_ID}.txt"  
  paperclip cat /papers/$PAPER\_ID/meta.json \> "${PAPER\_ID}.meta.json"  
  \`\`\`  
    
  This exports Paperclip's parsed text, not necessarily the publisher's original  
  PDF. \`paperclip fetch \<DOI-or-URL\>\` uses browser cookies to place an accessible  
  paper in your Paperclip clipboard; access to a publisher PDF still depends on  
  your subscription and the publisher's terms.  
    
  To retain a corpus paper inside Paperclip as a zero-copy clipboard link:  
    
  \`\`\`bash  
  paperclip cp /papers/$PAPER\_ID /clipboard/protein-diffusion/  
  \`\`\`  
    
  \#\# 5\. Determine whether an ML method has a GitHub repository  
    
  First look for evidence in the paper itself:  
    
  \`\`\`bash  
  paperclip scan \-i \-C 4 /papers/$PAPER\_ID/content.lines \\  
   "github.com" "code availability" "source code" "implementation"  
  \`\`\`  
    
  For every hit in a saved search, let Paperclip inspect each full paper:  
    
  \`\`\`bash  
  paperclip map \--from s\_4a2b61f6 \\  
   "Does this paper introduce or use an ML method with an official public code repository? Return the method name, repository URL, supporting line numbers, and one of official/third-party/not-found. Do not guess."  
  \`\`\`  
    
  Export that analysis using the returned \`m\_...\` result ID:  
    
  \`\`\`bash  
  paperclip results m\_9c8d7e6f \--save code-repositories.txt  
  \`\`\`  
    
  If the paper contains no URL, search the web or GitHub for the exact quoted  
  method name plus the paper title or DOI. Treat a repository as official only  
  when at least one strong link exists:  
    
  \- the paper or its Code Availability section links to it;  
  \- the repository README cites the same title/DOI and matches the authors or  
   institution; or  
  \- an author/project page links to it.  
    
  Record \`not found\` rather than guessing when only forks, reimplementations, or  
  same-name projects appear. Also note the license, archived status, last commit,  
  release/checkpoint availability, and exact commit used for reproducibility.  
    
  \#\# Minimal end-to-end recipe  
    
  \`\`\`bash  
  paperclip repo init my-ml-review "ML method and code review"  
  paperclip search \-s pmc,biorxiv,medrxiv,arxiv "YOUR QUERY" \-n 10  
  paperclip repo add PAPER\_ID "WHY THIS PAPER MATTERS" \--lines LSTART-LEND  
  paperclip scan \-i \-C 4 /papers/PAPER\_ID/content.lines \\  
   "github.com" "code availability" "source code"  
  paperclip repo commit \-m "Curate relevant papers and verify claims"  
  paperclip repo export markdown \-o my-ml-review.md  
  \`\`\`  
  


# Datasets

# Meta

- 

# Methods

Methods: running perturbations models on datasets

Sei Chang, Frank Yu, Cecilia Wu

Prompt: You are a principal engineer working on an agentic workflow to implement automatic benchmark design and implementation for perturbation biology. Describe how you would implement this agentic workflow and specify whether there are existing tools that are appropriate for the specified tasks. You are only scoped for this particular task. You do not implement anything else in the pipeline, but you should add small details about what the other parts of the project (e.g., input/output formats) should include to make this optimal.

Important details to include: what are some considerations about the proposed workflow, things to experiment and check so that we can provide suggestions on how to improve this workflow and ensure it runs well/robustly?

Project: Agentic benchmark design and implementation for chemical perturbation prediction on single-cell transcriptomics

Task: Design agent-based pipeline for running a designed perturbation benchmark

* Note: this pipeline does not handle benchmark design, we simply want to run the benchmark given a prior specified dataset, metrics, and a list of models to benchmark  
* extracting details from the paper  
  * what is given: github repo, paper pdf  
  * extract relevant context to feed into the agent so it knows how to run the perturbation model: methods section, results   
* create harness around the model  
  * install correct packages  
  * find what inputs it requires (preprocessing, how many genes, etc.)  
  * perhaps also extract from the methods section of the paper for additional context?  
  * repository scanning (README, source code)  
* input dataset: use OpenProblems toy dataset for now (train/val/test/)  
* output: perturbation predictions and metrics (specified by OpenProblems)  
* final: potential downstream visualization)

## **What changes**

**1\. My box is two nodes in the §9 pipeline, not the whole thing.** I own **sandboxed reproduction agent** \+ **benchmark adapter generator**. Vlad's literature agent feeds me, Eeshan's verifier audits me, Philipp/Lijun own dataset harmonization, Matt owns metrics. Most of the leakage-audit apparatus I proposed belongs to Eeshan, and OP3 already enforces the important part structurally — regular methods never receive `de_test`; only explicitly marked control methods do. I should lean on that rather than rebuild it.

**2\. The terminal artifact is a Viash component \+ PR, not an abstract "adapter registry."** That's better than what I proposed, because Viash already gives you the container spec, the CLI contract, and a test harness. Target:

src/methods/\<method\_id\>/

  config.vsh.yaml    \# \_\_merge\_\_: ../../api/comp\_method.yaml \+ docker setup \+ resources

  script.py          \# the adapter

  test.py

  MODELSPEC.json     \# every field carries PAPER\_ID:Lstart-Lend and repo file:line

  DEVIATIONS.md      \# every place the harness differs from the paper's stated protocol

The gate is `viash ns test --query <method_id>` passing. That is validation by a standard outside the agent's own reasoning — judging criterion \#3, for free, using infrastructure that already exists.

**3\. Provenance stops being hygiene and becomes a graded deliverable.** Criterion \#2 is *"can you reconstruct why the agent concluded what it did."* So `MODELSPEC.json` and the agent trajectory are demo assets, not internal QA artifacts.

## **Verdict on the team's tool shortlist**

**RepoLaunch — yes, and it composes better with Viash than I realized.** It reconstructs a Dockerfile deterministically from the committed image's layers via hard-coded logic, and organizes commands to rebuild and test the repo inside the container, emitting a testcase-status mapping. Two consequences:

* Viash's `engines.docker.setup` is a declarative list of install steps. RepoLaunch's layer→Dockerfile reconstruction feeds it through a deterministic transform. **The agent never writes the Dockerfile**, which removes the single largest source of run-to-run variance in my original design.  
* The testcase-status mapping is a far better environment-correctness gate than "did `import` succeed." If the repo's own tests pass in the image, you have external evidence the environment is right.

This replaces the Repo2Run recommendation from my earlier writeup. RepoLaunch supersedes it for your purposes.

**Serena — yes, but ordering matters.** It's LSP-backed, so `find_symbol` / `find_referencing_symbols` only resolve properly once dependencies are installed. Run it *against the built image*, after RepoLaunch, not before. Pre-build you get degraded resolution and the agent will draw wrong conclusions about entrypoints confidently. Concretely: RepoLaunch → mount repo into the resulting image → point Serena's language server there → then extract the ModelSpec.

**mini-SWE-agent — yes, specifically because it's minimal.** A bash-only loop produces a trajectory that is a linear, readable list of commands. That *is* the inspectability artifact. A heavier multi-agent framework would score worse on criterion \#2 while being no more capable at this task.

**Paperclip — Vlad's, but I need to specify the handoff.** Because it exposes line-numbered `content.lines`, every ModelSpec field can carry `PMC1234567:L210-L225`. Reuse the discipline already written into your own quick guide — *do not guess*, record `not found` rather than inferring, treat a repo as official only on a strong link, and record license, archived status, last commit, and **the exact commit used**. That last one is my hard input requirement: the literature agent must hand me a pinned SHA, never `main`.

**BenchFlow — right tool, wrong box.** It's a platform for evaluating AI models, particularly coding agents, on standardized reproducible benchmarks, with a runtime that spins up large numbers of sandboxes per submission to run evaluations at scale. That's a fit for §9's *"How to benchmark the agents"* — including the K-replicate variance experiment below — not for running perturbation models. Point Eeshan at it.

**Sundial** — my stage should emit structured JSON (ModelSpec \+ deviations \+ gauntlet results \+ cost/wall-clock) shaped for it, not prose. **latch-bio** I'd need to look at before recommending; nothing in my path obviously needs it if you're on Viash/Nextflow already.

## **The finding that should drive the PR**

The §"OpenProblem Setup" note confirms the gap I flagged: methods **consume `de_train` \+ `id_map`** and emit a `prediction` layer. That interface is expressible for the six existing Kaggle-derived methods, which operate natively in DE-signature space. It is **not expressible for chemCPA, CPA, biolord, or anything else that predicts single-cell expression** — those need the counts matrix that lives upstream of `process_dataset`, plus a benchmark-owned limma step to lift predictions back into DE space.

The first genuine "integrate a new paper method" attempt will hit this wall. So:

* **Demo path: pick methods that dodge it.** Chem-PerturBridge is ideal, and §10 already points there — a pretrained *compound representation* feeding a ridge/MLP that predicts DE directly from (embedding, cell\_type) is fully API-compatible. It gets you a real integration without needing an API change.  
* **PR path: file the extension as the finding.** An optional `--sc_train` input gated by a `requires_sc_counts` capability flag in the component config, plus a shared lift component. "We attempted to integrate a real paper method and discovered the task API can't express it, here's the proposed extension" is a stronger hackathon narrative than a green checkmark.

## **Revised gauntlet (leaner, given OP3 \+ Eeshan)**

Drop from my original: container-level leakage isolation, the shuffled-label collapse test, filesystem audit — OP3's workflow structure and Eeshan's auditor cover these. Keep, as `viash ns test` cases:

1. **Layer/unit conformance.** Still the top silent killer: a model emitting `logFC` scored against `clipped_sign_log10_pval` (bounded ±4, different meaning) produces garbage with no error. Assert range, sparsity, and sign symmetry against the declared layer.  
2. **`id_map` row-order and gene-space exactness.** Treat any invocation of the metric's `--resolve_genes` reconciliation as a hard failure, not a convenience.  
3. **Perturbation sensitivity.** Shuffle `sm_name` → predictions must change materially. Catches the model that has collapsed to predicting the training mean while still scoring respectably.  
4. **No network at inference.** A model re-downloading its own copy of the public data is a leak that OP3's structure won't catch.  
5. **Baselines: use OP3's six existing control methods as-is.** Don't write your own. The literature in your §3 — Systema, scArchon, Ahlmann-Eltze — all converge on simple baselines being competitive or better, so a new method that doesn't clear them is the expected outcome, not an alarm.

## **Hackathon-scale plan**

Cut entirely: multi-seed statistics, Nextflow scale-out, GPU determinism, multi-dataset, the certified registry.

1. **Hand-write one adapter first**, by hand, for a method that already exists in OP3. This teaches the Viash contract and gives you the golden reference the agent's output is compared against. Do not start with the agent.  
2. **RepoLaunch \+ Serena \+ mini-SWE-agent on a difficulty ladder of three papers** — one API-native (Chem-PerturBridge-style representation), one mid (needs preprocessing reconstruction), one that will fail (needs single-cell input).  
3. **Gauntlet as viash tests \+ ModelSpec/DEVIATIONS emission.**  
4. **K=3 replicate runs of the agent on one model.** Compare score spread across the three generated adapters against the spread between OP3's existing methods. If they're comparable, the pipeline is measuring itself. This is the headline empirical result and it maps directly to §11 contribution 5\.

**Demo the ladder including the failure.** A legible, explained failure scores better on criterion \#3 than an unexplained success, and the third rung produces the API-gap finding above.

## **Two things in the doc I'd push back on**

**"Numerical agreement with the paper" as an agent metric (§9) is a trap** — and your own §5 says why: method-paper results diverge because of preprocessing, gene panels, splits, priors, and aggregation. When my agent reproduces a paper and gets a different number, there are two live hypotheses (bad harness vs. different protocol) and the metric can't distinguish them. **Score the agent on whether `DEVIATIONS.md` explains the gap, not on matching the number.** The deviation record is what makes the disagreement scientifically interpretable, and it's the same artifact that stops the agent from silently "fixing" the model by adding an unspecified normalization or quietly cutting epochs.

**My box should be a second line of scope defense.** §11 calls chemical-vs-genetic classification one of the most consequential agent subtasks. The machine-checkable guard lives in my stage: if `MODELSPEC.perturbation_encoding` resolves to gene IDs rather than SMILES/fingerprint, the adapter generator should **refuse and return upstream** rather than heroically adapting a genetic method into the chemical task. Every such rejection is also labeled eval data for Vlad's scope classifier — which is a nice closed loop and cheap to build.

***Install dependencies and deliver as a docker image automatically \- RepoLaunch***  
RepoLaunch [https://github.com/microsoft/RepoLaunch](https://github.com/microsoft/RepoLaunch) \- Microsoft Research

* Install all dependencies and build the repository, delivered as a docker image, with docker image layer info collected for Dockerfile reconstruction;  
* Organize the command to rebuild the repository inside a container after repo modifications;  
* Organize command to test the repository, write a parser to parse test output into structured testcase-status mapping, and optionally find per-testcase running command.

***Semantic Repository scanning \- Serena***

[https://github.com/oraios/serena](https://github.com/oraios/serena) 

* An MCP Server   
* Achieve Symbol-level semantic retrieval via Language Server Protocol  
  * find\_symbol  
  * find\_referencing\_symbols  
  * get\_document\_overview  
  * find declaration  
  * find implementation  
  * Diagnostics

***mini-SWE-agent*** \- reasoning / control loop

[https://github.com/swe-agent/mini-swe-agent](https://github.com/swe-agent/mini-swe-agent) 

# Meeting notes

# Next meeting: saturday at 3:30 pm

# Saturday, after lunch

## Directions:

\- Matt – metrics for chemical perturbations. Metrics for metrics? Can agents propose new metrics?  
\- Philipp – dataset integration: checks, what is worth including  
\- Vlad – literature agent  
\- Lijun – data preprocessing, QC  
\- Eeshan – review / verifier agent. Sundial for reports  
\- Sei \+ Frank \+ Cecilia – new method  integration

## Things to watch for:

\- Type of evaluation – splits, tasks

# AI Deep Researches

# Perturbation Prediction Datasets

# **Deep-research kickoff: AI benchmarking and genetic perturbation prediction**

Your hackathon deck already defines a strong research hypothesis: an agent system should detect newly published methods, datasets, and metrics; reproduce their central results; adapt them to the Open Problems interface; and prepare a pull request and scientific report. Pages 4–7 describe separate literature, verification, data-analysis, and contribution stages, while page 8 proposes perturbation prediction and Chem-PerturBridge as the first case study.

## **1\. The first major finding: chemical and genetic perturbations are being mixed**

The current Open Problems **Perturbation Prediction** task is explicitly a **chemical perturbation** benchmark: it predicts how small molecules change gene expression in different cell types. It currently contains six submitted methods, six control methods, one dataset, and five rowwise metrics. Its dataset measures 144 compounds after 24 hours in PBMCs from three donors. ([Open Problems](https://openproblems.bio/results/perturbation_prediction))

Chem-PerturBridge is also chemical rather than genetic. It harmonizes more than 37,000 compounds, 136 cellular contexts, approximately 1.25 million transcriptomic samples, and eight assay types. Its main findings include weak cross-dataset agreement for exact log-fold-change magnitudes but more stable agreement in the **direction** of gene-expression changes. It also reports gains from Chem-PerturBridge-pretrained compound representations on a compound-held-out OP3 evaluation. ([arXiv](https://arxiv.org/abs/2605.31522))

A genetic perturbation benchmark, by contrast, must represent interventions such as gene knockout, CRISPR interference, CRISPR activation, combinations of genes, guide efficiency, and intervention strength. The two areas can share infrastructure, metrics, and agent workflows, but they should not share an undifferentiated leaderboard.

### **Recommended benchmark hierarchy**

| Track | Perturbation object | Essential metadata | Principal generalization questions |
| ----- | ----- | ----- | ----- |
| **Chemical** | Compound or compound combination | Structure, identifier, dose, exposure time, assay | Unseen molecule, dose, cell type, donor, dataset |
| **Genetic** | Gene or gene combination | Gene ID, knockout/CRISPRi/CRISPRa, guide, efficiency, time | Unseen gene, unseen combination, cell type, donor, dataset |
| **Cross-modal** | Chemical–target–genetic relationship | Compound, target genes, pathway and context | Whether chemical and genetic effects transfer or align |

The immediate project should therefore use Chem-PerturBridge to validate the **agentic benchmark-maintenance pipeline**, while creating a separate genetic perturbation task for the scientific benchmark.

---

## **2\. What general AI benchmarking research contributes**

Five lessons from broader AI evaluation are directly applicable.

### **Multi-metric evaluation is mandatory**

HELM was designed around a scenario taxonomy and evaluated models across accuracy, calibration, robustness, fairness, bias, toxicity, and efficiency rather than reporting accuracy alone. The general principle is that a benchmark should expose trade-offs instead of hiding them in one number. ([arXiv](https://arxiv.org/abs/2211.09110))

For perturbation prediction, the equivalent is to report expression error, perturbation discrimination, differential-expression recovery, distributional fidelity, biological fidelity, uncertainty, runtime, and reproducibility separately.

### **Benchmark composition can determine the “winner”**

The Benchmark Lottery demonstrates that changing the selected tasks can substantially change model rankings. It also argues that benchmarks implicitly encode what the field considers important. ([arXiv](https://arxiv.org/abs/2107.07002))

For perturbation models, rankings may change when the benchmark emphasizes:

* Strong versus weak perturbations.  
* Single genes versus combinations.  
* Cancer cell lines versus primary cells.  
* Mean expression versus full cellular distributions.  
* Within-dataset versus cross-dataset generalization.  
* Magnitude accuracy versus direction or retrieval.

Therefore, a claim such as “model A is best” is scientifically weak unless the scenario and metric are named.

### **Holdouts, cost, and reproducibility belong in the scorecard**

*AI Agents That Matter* identifies inadequate holdout sets, a narrow focus on accuracy, missing cost comparisons, and inconsistent evaluation practices as central problems in agent benchmarks. ([arXiv](https://arxiv.org/abs/2407.01502))

A benchmark-maintenance agent should consequently be evaluated not just on whether it eventually produces a pull request, but also on compute cost, wall-clock time, failure rate, reproducibility, use of hidden test cases, and the amount of human correction required.

### **Scientific-agent tasks should be hierarchically decomposed**

PaperBench decomposes the replication of 20 AI papers into 8,316 gradable subtasks using author-informed hierarchical rubrics. The best tested agent at its release achieved a 21% average replication score. ([OpenAI](https://openai.com/index/paperbench/))

CORE-Bench similarly evaluates computational reproduction using 270 tasks derived from 90 papers across computer science, social science, and medicine. Its hardest task level also yielded 21% accuracy for the best reported baseline. ([arXiv](https://arxiv.org/abs/2409.11363))

These results imply that “reproduced the paper” is too coarse a label. For a perturbation paper, the rubric should separately score:

1. Correct identification of the prediction task.  
2. Correct dataset and split reconstruction.  
3. Environment and dependency recovery.  
4. Reproduction of a baseline.  
5. Reproduction of the central result.  
6. Agreement within a defined numerical tolerance.  
7. Detection of leakage or scientific limitations.  
8. Generation of a valid benchmark adapter and tests.

### **A living benchmark needs versioned releases**

The leaderboard must preserve past releases rather than silently replacing them. Each release should freeze datasets, processing, splits, metric versions, code commits, container images, external knowledge sources, and compute budgets. New papers can then produce a new release without invalidating previous results.

---

## **3\. Current perturbation-prediction benchmark landscape**

| Resource | Scope | Main lesson for this project |
| ----- | ----- | ----- |
| **Open Problems OP3** | Chemical, cross-cell-type prediction | Provides a real modular integration target, but currently has one dataset, five closely related rowwise metrics, and methods that are largely inherited from the NeurIPS competition. ([Open Problems](https://openproblems.bio/results/perturbation_prediction)) |
| **Benchmarking algorithms for generalizable single-cell perturbation response prediction** | Genetic and chemical; 27 methods, 29 datasets, 6 metrics | Demonstrates that broad evaluation across cellular-context and perturbation-generalization scenarios is feasible and that context representation is central to generalization. ([Nature](https://www.nature.com/articles/s41592-025-02980-0)) |
| **PerturBench** | Genetic and chemical | Finds mode-collapse problems, shows that rank metrics complement RMSE, and reports that simple architectures are often competitive with more complex models. ([arXiv](https://arxiv.org/abs/2408.10609)) |
| **Systema** | Genetic; ten datasets | Shows that common metrics can reward systematic differences shared by most perturbed cells rather than gene-specific biology; simple perturbed-mean or matching-mean baselines can equal or outperform sophisticated methods. ([Nature](https://www.nature.com/articles/s41587-025-02777-8)) |
| **Ahlmann-Eltze, Huber and Anders** | Genetic; foundation and deep-learning models | Five foundation models and two other deep-learning approaches failed to outperform deliberately simple baselines in the evaluated settings. ([Nature](https://www.nature.com/articles/s41592-025-02772-6)) |
| **scArchon** | Non-genetic response transfer; nine tools and six datasets | Shows that rankings depend strongly on the dataset and metric, dimensionality-reduction plots can be misleading, several methods can fall below a linear or control baseline, and biological enrichment predictions can contain spurious terms. ([Springer](https://link.springer.com/article/10.1186/s13059-026-04104-z)) |
| **Chem-PerturBridge** | Chemical, cross-dataset harmonization | Suggests that direction and retrieval may be more transferable than exact effect magnitude, and is an excellent case for testing dataset, metric, and representation agents. ([arXiv](https://arxiv.org/abs/2605.31522)) |

The literature is converging on a crucial point: **the central unsolved problem is no longer merely model architecture. It is defining an evaluation that measures perturbation-specific biological information rather than easy global structure.**

---

## **4\. Scientific foundations of genetic perturbation prediction**

Perturb-seq established the experimental foundation by combining pooled CRISPR perturbations with single-cell RNA sequencing. The original work analyzed approximately 200,000 cells and demonstrated recovery of gene targets, gene programs, cellular states, and genetic interactions. ([PubMed](https://pubmed.ncbi.nlm.nih.gov/27984732/))

The Norman et al. combinatorial CRISPRa study produced a widely used genetic-interaction dataset. It used high-dimensional transcriptional phenotypes to characterize interaction manifolds and demonstrated a recommender-system approach for predicting unmeasured genetic interactions. ([PubMed](https://pubmed.ncbi.nlm.nih.gov/31395745/))

The scPerturb resource subsequently harmonized 44 public perturbation-response datasets spanning transcriptomic, proteomic, and epigenomic readouts. It also introduced energy statistics as a way to quantify differences between single-cell populations. ([Nature](https://www.nature.com/articles/s41592-023-02144-y))

These data sources support several distinct prediction targets:

* **Pseudobulk effect prediction:** predict an average log-fold-change or post-perturbation expression vector.  
* **Single-cell distribution prediction:** predict the distribution of cell states rather than only its mean.  
* **Differential-expression prediction:** identify which genes change and in which direction.  
* **Genetic-interaction prediction:** predict synergy, suppression, epistasis, redundancy, or neomorphism.  
* **Functional phenotype prediction:** predict pathways, cell-state composition, proliferation, death, or another downstream phenotype.

A benchmark should not treat these as interchangeable tasks.

---

## **5\. Representative model literature—and why reported rankings conflict**

GEARS uses gene-relation graphs and graph neural networks to predict single- and multigene perturbations. Its original paper reported higher precision for several genetic-interaction classes and emphasized combinations containing genes not experimentally observed during training. ([PubMed](https://pubmed.ncbi.nlm.nih.gov/37592036/))

Biolord uses a disentangled representation and reported lower normalized mean-squared error than GEARS on several unseen single- and double-gene settings. ([Nature](https://www.nature.com/articles/s41587-023-02079-x))

Scouter represents perturbations using embeddings generated by language models and reported substantially lower errors than GEARS and biolord across five datasets under the paper’s evaluation protocol. ([Nature](https://www.nature.com/articles/s43588-025-00912-8))

TxPert uses multiple complementary biological and high-throughput knowledge graphs. Its paper reports performance approaching split-half experimental reproducibility for unseen single perturbations and improvements in harder combination and cross-cell-line settings. ([Nature](https://www.nature.com/articles/s41587-026-03113-4))

GPerturb takes a different approach: sparse Gaussian-process perturbation regression, which is attractive for interpreting individual gene effects and modeling uncertainty. ([Nature](https://www.nature.com/articles/s41467-025-61165-7))

These method-paper results do not necessarily contradict independent benchmarks. They are frequently based on different preprocessing, gene panels, split definitions, external priors, metrics, baselines, and aggregation strategies. Systema and the linear-baseline study show that changing these choices can greatly reduce apparent gains from complex architectures. ([Nature](https://www.nature.com/articles/s41587-025-02777-8))

### **Emerging 2026 directions**

Recent preprints are moving toward:

* Sequence- and regulatory-prior conditioning for zero-shot genes, as in CisTransCell. ([arXiv](https://arxiv.org/abs/2606.13713))  
* Distribution-level diffusion and flow models rather than point prediction, as in PerturbDiff and latent causal diffusion models. ([arXiv](https://arxiv.org/abs/2602.19685))  
* Decomposition of responses into global, perturbation-specific, cell-context-specific, and interaction components. A July 2026 preprint reports that relatively simple models can become competitive when biological priors are aligned with the appropriate response component. ([bioRxiv](https://www.biorxiv.org/content/10.64898/2026.07.24.740459v1))  
* A formal taxonomy of evaluation protocols separating representation, metric, score transformation, and reporting choices, accompanied by the scPertEval implementation. ([bioRxiv](https://www.biorxiv.org/content/10.64898/2026.07.23.740433v1))

These are promising but should initially be placed in a **watchlist** rather than declared benchmark winners until they have been reproduced under common splits and baselines.

---

## **6\. Recommended genetic perturbation benchmark specification**

### **6.1 Formal task**

For context (c), basal cellular state (X\_0), and perturbation set (p), estimate:

\[  
P(X\_{\\text{post}} \\mid X\_0, p, c)  
\]

A simpler pseudobulk task estimates:

# **\[**

# **\\Delta\_{p,c}**

## **E\[X\_{\\text{post}}\\mid p,c\]**

E\[X\_{\\text{control}}\\mid c\]  
\]

For genetic perturbations, (p) must include:

* Target gene or genes.  
* Intervention type: knockout, CRISPRi, CRISPRa, or another technology.  
* Guide or construct identity where available.  
* Perturbation efficiency or on-target evidence.  
* Time since perturbation.  
* Cell line, cell type, donor, species, and assay.  
* Whether external gene information is allowed.

### **6.2 Generalization scenarios**

The benchmark should publish separate results for:

| Scenario | Scientific question |
| ----- | ----- |
| **S0: In-domain sanity** | Can the method reproduce held-out cells or replicates from known perturbations? |
| **S1: Unseen single gene** | Can it predict a gene never perturbed in training in the same cellular context? |
| **S2: Unseen combinations** | Can it predict pairs with zero, one, or both constituent genes individually observed? |
| **S3: Unseen donor or cell type** | Can a learned genetic effect transfer to a new biological context? |
| **S4: Cross-dataset or laboratory** | Does the model survive changes in protocol, batch, assay, and institution? |
| **S5: Biological-family holdout** | Can it extrapolate beyond closely related genes or pathways rather than interpolate between neighbors? |
| **S6: Cross-species** | Is any higher-order regulatory response conserved? |

For models using Gene Ontology, interaction networks, sequences, language-model embeddings, or foundation-model pretraining, the benchmark should publish two tracks:

* **Declared-prior track:** external biological knowledge is permitted and versioned.  
* **Strict inductive track:** only training-fold perturbation data and predefined generic metadata are allowed.

This prevents an “unseen gene” claim from quietly benefiting from information derived from that gene elsewhere.

---

## **7\. Metric suite**

A credible benchmark needs complementary metric families rather than five variants of global expression similarity.

| Metric family | Candidate measures | Failure mode detected |
| ----- | ----- | ----- |
| **Absolute expression fit** | RMSE, MAE, (R^2), Pearson, Spearman | Overall numerical mismatch |
| **Perturbation-specific effect** | Systema-centered correlations and errors | Prediction of a generic “perturbed” state instead of the target gene’s effect |
| **Discrimination and retrieval** | Rank of the correct perturbation among same-context decoys; PrtR-type criteria | Predictions that look plausible but are not perturbation-specific |
| **Differential-expression recovery** | Precision, recall, AUPRC, signed top-(k) overlap | Incorrect responsive genes or directions |
| **Distributional fidelity** | Wasserstein distance, MMD, energy distance | Correct mean but incorrect heterogeneity or subpopulation structure |
| **Biological fidelity** | Pathway precision/recall, semantic similarity, genetic-interaction class | Biologically implausible downstream conclusions |
| **Calibration** | Prediction intervals, empirical coverage, calibration error | Confident predictions in low-signal or unseen settings |
| **Operational quality** | Runtime, memory, compute cost, failures, reproducibility | Impractical or fragile methods |

### **Two statistical protections are especially important**

**Independent control estimation.** A May 2026 preprint shows that reusing the same control population to construct both predicted and observed differential-expression quantities can inflate cosine and correlation scores, even for uninformative predictions. It proposes splitting the control population to remove this shared-noise bias. ([bioRxiv](https://www.biorxiv.org/content/10.64898/2026.05.07.723486v1))

**Perturbation-centered evaluation.** Systema shows that measuring every perturbation relative to controls can reward a shared global treatment or stress response. Re-centering around the mean perturbed state better isolates what distinguishes one perturbation from another. ([Nature](https://www.nature.com/articles/s41587-025-02777-8))

The benchmark should therefore calculate both conventional control-relative metrics and corrected perturbation-specific metrics.

### **Composite scores**

A single unqualified overall score should not be the primary result. Metric correlations can duplicate the weight of one property, and task selection can reverse rankings. scArchon explicitly removed highly correlated metrics before calculating its composite, while the Benchmark Lottery shows how benchmark subsets alter winners. ([Springer](https://link.springer.com/article/10.1186/s13059-026-04104-z))

The preferred presentation is:

1. Per-scenario scorecards.  
2. Per-dataset results.  
3. Confidence intervals across perturbations—not individual cells.  
4. A Pareto view of accuracy, biological fidelity, cost, and robustness.  
5. A clearly documented composite only as a secondary summary.

---

## **8\. Baseline suite**

Every model should be required to beat the following baselines:

1. **No-effect baseline:** return the matched control state.  
2. **Perturbed-mean baseline:** return the average training perturbation response.  
3. **Mean per gene or context:** where scientifically valid.  
4. **Additive or matching-mean combination baseline:** construct a pair from its single-gene effects.  
5. **Linear or ridge regression.**  
6. **Nearest-neighbor prediction** using fixed gene embeddings.  
7. **Split-half experimental reproducibility:** an estimate of measurement noise and the attainable ceiling.

The first benchmark release should include only a small number of advanced models, for example GEARS, biolord, one recent prior-based method such as Scouter or TxPert, and one uncertainty- or distribution-aware method. A broad model count is less important initially than ensuring that every implementation uses identical data, splits, and evaluation code.

---

## **9\. Agentic architecture for maintaining the benchmark**

The deck’s literature–verifier–contributor design can be expanded into the following controlled pipeline:

Paper scout  
   ↓  
Scope and relevance classifier  
   ↓  
Method/data/metric schema extractor  
   ↓  
Artifact and license resolver  
   ↓  
Sandboxed reproduction agent  
   ↓  
Benchmark adapter generator  
   ↓  
Leakage and scientific-audit agent  
   ↓  
Benchmark-impact analysis  
   ↓  
Report and pull-request generator  
   ↓  
Human scientific approval

### **Agent responsibilities**

**Paper scout:** monitors papers and preprints and identifies candidate contributions.

**Scope classifier:** determines chemical versus genetic perturbation, prediction target, expected input/output schema, and whether the work genuinely matches an existing task. Chem-PerturBridge should serve as a gold test of this capability: it is relevant to OP3 but should not be mislabeled as a genetic method.

**Artifact resolver:** freezes the paper version, source commit, model weights, environment, data identifiers, checksums, and licenses.

**Reproduction agent:** first runs the smallest meaningful experiment—one fold, one dataset slice, one baseline, and one central result.

**Adapter generator:** translates the reproduced artifact into the Open Problems component interface without changing the model’s scientific behavior.

**Scientific auditor:** checks data leakage, improperly shared controls, weak baselines, unsupported preprocessing, test-set tuning, missing metadata, and metric redundancy.

**Benchmark analyst:** estimates whether adding the component changes rankings, reveals a new edge case, duplicates an existing metric, or creates prohibitive compute costs.

**Contributor:** creates a report and pull request but does not merge it automatically. New code should execute in an isolated environment because papers and repositories are untrusted inputs.

### **How to benchmark the agents**

The agent benchmark should measure:

* Relevance precision and recall.  
* Chemical-versus-genetic scope accuracy.  
* Metadata extraction accuracy.  
* Environment reconstruction success.  
* Numerical agreement with the paper.  
* Unit- and integration-test pass rate.  
* Detection of leakage and invalid evaluation.  
* Correctness of the generated benchmark adapter.  
* Human review time and number of requested changes.  
* PR acceptance rate.  
* Compute cost, wall-clock time, and failure rate.  
* Security-policy violations.

A retrospective corpus can provide gold-standard outcomes: previously integrated components, deliberately irrelevant papers, papers with reproducibility failures, duplicated metrics, and datasets with licensing or leakage problems. A temporal test set consisting of later papers would provide a genuine holdout.

---

## **10\. Hackathon-scale minimum viable research program**

### **Chemical pipeline demonstration**

Use Chem-PerturBridge only as a bounded proof of the agent workflow:

1. Select one small cross-dataset matched-condition slice.  
2. Reproduce one agreement analysis and one OP3 held-out-compound experiment.  
3. Implement signed direction agreement.  
4. Implement perturbation retrieval against same-context, different-compound decoys.  
5. Add one simple pretrained compound-representation baseline.  
6. Generate provenance, tests, a result report, and a proposed OP3 pull request.

The full 1.25-million-sample resource should not be ingested during the initial implementation.

### **Separate genetic benchmark demonstration**

Use a Norman combinatorial subset plus a Replogle or scPerturb-derived single-gene subset.

The minimum model set should be:

* No effect.  
* Perturbed mean.  
* Matching mean or additive singleton.  
* Ridge regression.  
* One established advanced method, such as GEARS.  
* Optionally one recent prior-aware model.

The minimum metric set should be:

* RMSE on expression changes.  
* Independent-control delta correlation.  
* Systema-style perturbation-specific score.  
* Signed differential-expression recall and precision.  
* Correct-perturbation retrieval.  
* Genetic-interaction classification for the Norman subset.

The MVP succeeds when the complete subset is reproducible from a clean environment and the agent produces a scientifically reviewable contribution—not when it completes a full-scale leaderboard or claims a new state of the art.

---

## **11\. Proposed research-paper direction**

### **Candidate title**

**AgenticBench-Perturb: A Living, Reproducible Benchmark for Genetic Perturbation Response Prediction**

### **Central thesis**

Current perturbation model rankings are unstable because datasets, split definitions, control construction, metrics, baselines, and external priors differ across studies. A versioned, modality-aware benchmark—maintained by agents but governed by humans—can measure perturbation-specific biological generalization more reliably and reduce the cost of incorporating new research.

### **Main contributions**

1. **A benchmark ontology** separating chemical, genetic, and cross-modal perturbations.  
2. **Leakage-resistant generalization scenarios** for unseen genes, combinations, contexts, datasets, and biological families.  
3. **A metric-audit suite** incorporating independent-control estimation, perturbation-centered effects, retrieval, differential expression, distributions, and biological fidelity.  
4. **A strong baseline suite** designed to reveal whether models learn target-specific effects.  
5. **An agent benchmark** for paper discovery, reproduction, adaptation, scientific auditing, and PR generation.  
6. **A retrospective ranking-stability analysis** measuring how model conclusions change across splits, metrics, gene panels, and score aggregation.  
7. **A prospective demonstration** in which the system processes newly published perturbation papers under a temporal holdout.

### **High-value hypotheses**

* Model rankings will change materially across conventional and perturbation-specific metrics.  
* A substantial portion of apparent performance will be explained by global systematic variation or shared-control bias.  
* Direction, discrimination, and retrieval will transfer across datasets better than exact expression magnitude.  
* Biological priors will help primarily when they align with the response component being predicted.  
* Agents will reduce integration time but will remain unreliable enough that scientific approval and sandboxed execution are necessary.  
* Scope classification—especially distinguishing chemical from genetic interventions—will be one of the most consequential agent subtasks.

The next concrete research artifact should be a **versioned evidence matrix** with one row per benchmark, dataset, method, or metric and fields for modality, prediction target, split, external priors, baselines, metrics, code availability, reproducibility status, compute requirements, licensing, and known failure modes. That matrix can serve simultaneously as the literature review, benchmark registry, and gold corpus for the literature and verifier agents.

# Tracks

*Logistics • Track A • Co-Scientist*

**Judging:**

1. **Closing the Loop:** does the agent analyze data it hasn’t seen and propose a next experiment that changes when the results change?  
2. **Inspectability:** can you reconstruct why the agent concluded what it did?  
3. **Validation:** how do you know the output is correct, by some standard outside the agent’s own reasoning?  
4. **Creative use of sponsor tools\!**

*Logistics • Track B • Dataset/Meta-Analysis*

What have you always wanted the literature to tell you, but could never read fast enough to find out? Draft the queries, run them across thousands of papers, sharpen and re-run until the results hold the specific pieces you care about. Then the real work: find the pattern in what you assembled that no single paper could show you, and demo that.

**Judging:**

1. **Comprehensiveness:** did you defensibly cover the relevant corpus, and can you say what you excluded and why?  
2. **Provenance:** can every claim-row be traced to the paper and line it came from?  
3. **Insight at Scale:** does the data you assembled reveal something beyond what you can see reading one paper at a time?  
4. **Creative use of sponsor tools\!**

# Random Notes Philipp

- Which tools from the hackathon might be helpful:  
  - paperclip  
    - find new papers  
  - benchflow?  
  - latch-bio  
- On a high-level there are two tasks:  
  - 1\) Extend existing tasks  
    - Here we already well defined tasks  
  - 2\) Define new tasks  
    - Have an agent running one every week that checks for benchmark papers in the single-cell space; and suggesting benchmarks that could be ingested into OpenProblems.  
      - What are guidelines here? What make a benchmark paper suited to be included in OpenProblems  
- LLM \- human :  
  - Human:  
    - Define the task:  
      - How to split the data  
      - How to evaluate  
    - Optional:  
      - Provide relevant model papers as seeds  
      - Provide relevant benchmark papers as seed  
      - Provide relevant dataset as seed  
  - LLM:  
    - Fetch and process dataset (ingest into open problems)  
    -   
- Template / skill to add tasks to open problems:  
  - Clearly state what is takes to add something to open problems  
  - Maybe:  
    - Use paperclip to find relevant papers  
- Blockers:  
  - Full-text paper access  
- Ideas:  
  - How to best evaluate whether new benchmarks are good or not?  
  - How can evaluate the agent traces? what rubrics are important?  
- How do we know that a chemical perturbation dataset is well designed?  
- What are the key characteristics per dataset:  
- Notes:  
  - Check also Thaddeus work again\!  
- Adata layout:  
  - .layers\[“count”\]  
  - obs  
    - group column (e.g. which cell type, etc.)  
    - perturbation column (e.g. which small molecules \-\> smile OR?)  
    - perturbation dose  
    - perturbation time  
    - batch column  
  - uns  
    - meta  
      - control\_tag (e.g. non-targeting controls)  
- As new test case we would need a recently published small molecule perturbation dataset  
  - but I am not sure if there is something like this out there  
- Datasets (single-cell with small molecule perturbations):  
  - Kaggle OP3 (currently on open problems)  
  - CIGS  
  - Tahoe100M  
  - Sciplex \-\> this could be a good use case because the size is manageable (and maybe our analysis would flag quality issues)  
- What must be part of the workflow:  
  - Harmonize adata scheme (see above)  
  - Harmonize chemical structure identifier   
    - Desalt smiles  
    - Fetch InChikey?  
  - Cells filtering  
    - min thresholds, etc.?  
  - Gene space filtering:  
    - Protein coding genes  
  - DE analysis:  
    - Compute DEGs \-\> to what extend could we provide general guidelines here? Maybe for now just do t-test but taking the   
  - Dynamic range fraction analysis:  
    - See also how hugo had set it up?  
- What to improve in the workflow:  
  - Improve the DE pipeline

# OpenProblem Setup

### Adding Tasks (here from https://github.com/openproblems-bio/task\_perturbation\_prediction)

1. **Task metadata**  
   viash.yaml (e.g task\_perturbation\_prediction/\_viash.yaml) identifies the task, its scientific objective, authors, version, license, and Open Problems organization settings.  
2. **Typed API contracts**  
   Files under \`src/api\` (e.g. task\_perturbation\_prediction/src/api) define the accepted schemas for datasets, methods, predictions, metrics, and scores. These contracts are the main interoperability boundary.  
3. **Dataset standardization**  
   The processing workflow (e.g. task\_perturbation\_prediction/src/workflows/process\_dataset/main.nf) filters cells and genes, computes pseudobulk profiles, runs Limma, and constructs:  
   * `de_train.h5ad`: visible training differential-expression profiles  
   * `de_test.h5ad`: held-out private-test ground truth  
   * `id_map.csv`: ordered target `(cell_type, small_molecule)` combinations  
4. **Pluggable methods**  
   Every method implements the same method interface (e.g. task\_perturbation\_prediction/src/api/wf\_method.yaml): consume `de_train` and `id_map`, select a DE layer, and emit a prediction. The required output is an AnnData file containing a `prediction` layer plus `dataset_id` and `method_id` metadata, as defined in file\_prediction.yaml (e.g. task\_perturbation\_prediction/src/api/file\_prediction.yaml).  
5. **Independent scoring components**  
   Metrics receive the prediction and hidden `de_test` data through the metric interface (e.g. task\_perturbation\_prediction/src/api/comp\_metric.yaml). They currently calculate row-wise error and correlation measures and produce standardized score metadata.  
6. **Benchmark orchestration**  
   The benchmark workflow (e.g. task\_perturbation\_prediction/src/workflows/run\_benchmark/main.nf) fans out across registered methods, evaluates every prediction with the registered metrics, then gathers scores and task/dataset/method metadata. Regular methods never receive `de_test`; only explicitly marked control methods do.

# Metrics

Papers:  
[https://www.biorxiv.org/content/10.64898/2026.07.23.740433v1](https://www.biorxiv.org/content/10.64898/2026.07.23.740433v1)  
[https://arxiv.org/abs/2605.31522](https://arxiv.org/abs/2605.31522)  
[https://www.nature.com/articles/s41592-023-01814-1](https://www.nature.com/articles/s41592-023-01814-1)  
[https://arxiv.org/abs/2506.22641](https://arxiv.org/abs/2506.22641)  
[https://www.biorxiv.org/content/10.1101/2025.10.20.683304v1.abstract](https://www.biorxiv.org/content/10.1101/2025.10.20.683304v1.abstract)

Approach to building the metametric:

Define datasets and models to evaluate against

# Review

