import { useEffect, useRef, useState } from "react";
import "./App.css";
import DocumentEditorComponent from "../components/DocumentEditor";

const API_URL = "http://localhost:8000";

function Icon({ name, size = 22 }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true
  };

  const paths = {
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h8" /></>,
    upload: <><path d="M12 16V4m-5 5 5-5 5 5" /><path d="M20 16.5v2A2.5 2.5 0 0 1 17.5 21h-11A2.5 2.5 0 0 1 4 18.5v-2" /></>,
    briefcase: <><rect x="3" y="7" width="18" height="14" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18M10 12v2h4v-2" /></>,
    sparkles: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" /><path d="m19 14 1.1 2.9L23 18l-2.9 1.1L19 22l-1.1-2.9L15 18l2.9-1.1L19 14ZM5 2l.8 2.2L8 5l-2.2.8L5 8l-.8-2.2L2 5l2.2-.8L5 2Z" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
    trash: <><path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m4 4v6m6-6v6" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" /></>
  };

  return <svg {...common}>{paths[name]}</svg>;
}

function App() {
  const [masterResume, setMasterResume] = useState(null);
  const [resumeFile, setResumeFile] = useState(null);
  const [jobDescription, setJobDescription] = useState("");
  const [replaceResume, setReplaceResume] = useState(false);
  const [loading, setLoading] = useState(false);
  const [checkingResume, setCheckingResume] = useState(true);
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [generatedFilename, setGeneratedFilename] = useState(null);
  const [dragging, setDragging] = useState(false);

  const fileInputRef = useRef(null);

  useEffect(() => {
    async function fetchLatestResume() {
      try {
        const response = await fetch(`${API_URL}/resumes/latest`);

        if (!response.ok) {
          if (response.status === 404) {
            setMasterResume(null);
            return;
          }
          throw new Error("Failed to check for an existing resume.");
        }

        setMasterResume(await response.json());
      } catch (err) {
        setError(err.message);
      } finally {
        setCheckingResume(false);
      }
    }

    fetchLatestResume();
  }, []);

  function selectFile(file) {
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".docx")) {
      setError("Please select a Word document (.docx).");
      return;
    }

    setError("");
    setResumeFile(file);
    setGeneratedFilename(null);
  }

  async function uploadResume() {
    if (!resumeFile) return masterResume?.id;

    const formData = new FormData();
    formData.append("file", resumeFile);

    const response = await fetch(
      `${API_URL}/resumes/upload?replace=${replaceResume}`,
      {
        method: "POST",
        body: formData
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Resume upload failed.");
    }

    setMasterResume(data);
    setResumeFile(null);

    return data.id;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setAnalysis(null);
    setGeneratedFilename(null);

    if (!jobDescription.trim()) {
      setError("Please enter a job description.");
      return;
    }

    if (!resumeFile && !masterResume) {
      setError("Please upload a resume first.");
      return;
    }

    setLoading(true);

    try {
      const resumeId = await uploadResume();

      if (!resumeId) {
        throw new Error("Could not identify the master resume.");
      }

      const analysisResponse = await fetch(
        `${API_URL}/resumes/${resumeId}/analyze`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_description: jobDescription })
        }
      );

      const analysisData = await analysisResponse.json();

      if (!analysisResponse.ok) {
        throw new Error(analysisData.detail || "Resume analysis failed.");
      }

      setAnalysis(analysisData.processed_data);

      const generationResponse = await fetch(
        `${API_URL}/resumes/${resumeId}/generate`,
        { method: "POST" }
      );

      const generationData = await generationResponse.json();

      if (!generationResponse.ok) {
        throw new Error(
          generationData.detail || "Resume generation failed."
        );
      }

      if (!generationData.filename) {
        throw new Error("No generated filename was returned.");
      }

      setGeneratedFilename(generationData.filename);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (generatedFilename) {
    return (
      <div className="editor-workspace">
        <DocumentEditorComponent filename={generatedFilename} />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/" aria-label="AI Resume Builder home">
          <span className="brand-icon"><Icon name="file" size={27} /><span>✦</span></span>
          <span>AI Resume <strong>Builder</strong></span>
        </a>

        <div className="topbar-label">
          <span className="status-dot" />
          AI-powered resume workspace
        </div>
      </header>

      <main className="main-content">
        <section className="hero">
          <div className="hero-copy">
            <span className="eyebrow"><Icon name="sparkles" size={15} /> YOUR NEXT OPPORTUNITY STARTS HERE</span>
            <h1>Craft your perfect resume <span>with AI.</span></h1>
            <p>Turn your experience into a tailored resume that speaks directly to the role you want.</p>
          </div>
          <div className="hero-decoration" aria-hidden="true">
            <div className="decoration-card">
              <Icon name="file" size={66} />
              <span /><span /><span /><span />
              <div className="decoration-sparkle">✦</div>
            </div>
            <div className="decoration-orbit">✦</div>
          </div>
        </section>

        <div className="workspace">
          <aside className="sidebar">
            <div className="steps-card">
              <p className="sidebar-heading">YOUR WORKFLOW</p>

              <div className="step active">
                <div className="step-number">1</div>
                <div><h3>Upload resume</h3><p>Start with your experience</p></div>
              </div>

              <div className="step-line" />

              <div className="step">
                <div className="step-number">2</div>
                <div><h3>Add job description</h3><p>Tell us about your target role</p></div>
              </div>

              <div className="step-line" />

              <div className="step">
                <div className="step-number">3</div>
                <div><h3>Analyse & generate</h3><p>Build your tailored resume</p></div>
              </div>
            </div>

            <div className="sidebar-promo">
              <div className="promo-icon"><Icon name="sparkles" size={27} /></div>
              <h3>Make every application count.</h3>
              <p>Highlight the experience that matters for the opportunity ahead.</p>
              <span>Built around your experience <Icon name="arrow" size={16} /></span>
            </div>
          </aside>

          <form className="form-content" onSubmit={handleSubmit}>
            <section className="card resume-card">
              <div className="card-heading">
                <div className="heading-icon"><Icon name="upload" size={23} /></div>
                <div>
                  <h2>Your resume</h2>
                  <p>Upload your existing resume or use your saved version.</p>
                </div>
              </div>

              {checkingResume ? (
                <div className="existing-resume loading-resume">Checking for an existing resume...</div>
              ) : masterResume && !resumeFile ? (
                <div className="existing-resume">
                  <div className="file-icon"><Icon name="file" size={22} /></div>
                  <div className="file-details">
                    <strong>{masterResume.file_name || "Your saved resume"}</strong>
                    <span>Existing master resume</span>
                  </div>
                  <span className="ready-badge"><Icon name="check" size={15} /> Ready</span>
                </div>
              ) : null}

              <div
                className={`dropzone ${dragging ? "dragging" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  selectFile(event.dataTransfer.files[0]);
                }}
                onClick={() => fileInputRef.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    fileInputRef.current?.click();
                  }
                }}
              >
                <div className="dropzone-icon"><Icon name="upload" size={30} /></div>
                <h3>{resumeFile ? "Choose a different resume" : "Drop your resume here"}</h3>
                <p>or browse files from your device</p>
                <button type="button" className="browse-button" onClick={(event) => {
                  event.stopPropagation();
                  fileInputRef.current?.click();
                }}>
                  Browse files <Icon name="arrow" size={16} />
                </button>
                <span className="file-hint">DOCX format · Word documents only</span>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".docx"
                  hidden
                  onChange={(event) => selectFile(event.target.files[0] || null)}
                />
              </div>

              {resumeFile && (
                <div className="existing-resume selected-file">
                  <div className="file-icon"><Icon name="file" size={22} /></div>
                  <div className="file-details">
                    <strong>{resumeFile.name}</strong>
                    <span>{(resumeFile.size / 1024).toFixed(1)} KB · Selected file</span>
                  </div>
                  <button type="button" className="remove-file" aria-label="Remove selected file" onClick={() => setResumeFile(null)}>
                    <Icon name="trash" size={18} />
                  </button>
                </div>
              )}

              {masterResume && (
                <label className="replace-option">
                  <input
                    type="checkbox"
                    checked={replaceResume}
                    onChange={(event) => setReplaceResume(event.target.checked)}
                  />
                  <span>Replace my existing master resume with this upload</span>
                </label>
              )}
            </section>

            <section className="card job-card">
              <div className="card-heading">
                <div className="heading-icon"><Icon name="briefcase" size={23} /></div>
                <div>
                  <h2>Job description</h2>
                  <p>Paste the job description for the role you're targeting.</p>
                </div>
              </div>

              <textarea
                value={jobDescription}
                onChange={(event) => setJobDescription(event.target.value)}
                placeholder="Paste the job description here. Include responsibilities, required skills, qualifications and experience..."
                rows={8}
                maxLength={10000}
              />
              <div className="textarea-footer">
                <span>Include as much detail as possible for a better match.</span>
                <span>{jobDescription.length.toLocaleString()} / 10,000</span>
              </div>
            </section>

            {error && <div className="error-message" role="alert">{error}</div>}

            <button className="analyse-button" type="submit" disabled={loading || checkingResume}>
              {loading ? (
                <><span className="spinner" /> Processing your resume...</>
              ) : (
                <><Icon name="sparkles" size={20} /> Analyse & generate resume <Icon name="arrow" size={19} /></>
              )}
            </button>

            <p className="privacy-note">Your resume is used to create a tailored version for your application.</p>
          </form>
        </div>

        {analysis && (
          <section className="card results-card">
            <div className="card-heading">
              <div className="heading-icon"><Icon name="sparkles" size={23} /></div>
              <div><h2>Analysis results</h2><p>Your resume tailoring data.</p></div>
            </div>
            <pre>{JSON.stringify(analysis, null, 2)}</pre>
          </section>
        )}

        {generatedFilename && (
          <section className="card editor-card">
            <div className="card-heading">
              <div className="heading-icon"><Icon name="file" size={23} /></div>
              <div><h2>Your tailored resume</h2><p>Review and edit your generated document below.</p></div>
            </div>
            <DocumentEditorComponent filename={generatedFilename} />
          </section>
        )}
      </main>

      <footer className="footer">
        <span>AI Resume Builder</span>
        <span>Make your next move count.</span>
      </footer>
    </div>
  );
}

export default App;