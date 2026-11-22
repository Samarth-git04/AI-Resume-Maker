import { useEffect, useState } from "react";
import "./App.css";
import DocumentEditorComponent from "../components/DocumentEditor";

const API_URL = "http://localhost:8000";

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

  useEffect(() => {
    async function fetchLatestResume() {
      try {
        const response = await fetch(`${API_URL}/resumes/latest`);

        if (!response.ok) {
          throw new Error("Failed to check for an existing resume.");
        }

        const data = await response.json();
        setMasterResume(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setCheckingResume(false);
      }
    }

    fetchLatestResume();
  }, []);

  async function uploadResume() {
    if (!resumeFile) {
      return masterResume?.id;
    }

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
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            job_description: jobDescription
          })
        }
      );

      const analysisData = await analysisResponse.json();

      if (!analysisResponse.ok) {
        throw new Error(
          analysisData.detail || "Resume analysis failed."
        );
      }

      setAnalysis(analysisData.processed_data);

      const generationResponse = await fetch(
        `${API_URL}/resumes/${resumeId}/generate`,
        {
          method: "POST"
        }
      );

      const generationData = await generationResponse.json();

      if (!generationResponse.ok) {
        throw new Error(
          generationData.detail || "Resume generation failed."
        );
      }

      if (!generationData.filename) {
        throw new Error(
          "Resume generation succeeded but no filename was returned."
        );
      }

      setGeneratedFilename(generationData.filename);

    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <h1>AI Resume Builder</h1>

      <form onSubmit={handleSubmit}>
        <section className="card">
          <h2>Master Resume</h2>

          {checkingResume ? (
            <p>Checking for an existing resume...</p>
          ) : masterResume && !resumeFile ? (
            <div>
              <p>
                Existing resume:{" "}
                {masterResume.file_name || "Uploaded resume"}
              </p>

              <label>
                <input
                  type="checkbox"
                  checked={replaceResume}
                  onChange={(event) =>
                    setReplaceResume(event.target.checked)
                  }
                />
                Replace existing resume
              </label>
            </div>
          ) : null}

          <input
            type="file"
            accept=".docx"
            onChange={(event) => {
              setResumeFile(event.target.files[0] || null);
            }}
          />

          {resumeFile && (
            <p>Selected file: {resumeFile.name}</p>
          )}
        </section>

        <section className="card">
          <h2>Job Description</h2>

          <textarea
            value={jobDescription}
            onChange={(event) =>
              setJobDescription(event.target.value)
            }
            placeholder="Paste the job description here..."
            rows={12}
          />
        </section>

        {error && (
          <p className="error">
            {error}
          </p>
        )}

        <button type="submit" disabled={loading || checkingResume}>
          {loading
            ? "Processing..."
            : "Analyse and Generate Resume"}
        </button>
      </form>

      {analysis && (
        <section className="card">
          <h2>Analysis Results</h2>

          <pre>
            {JSON.stringify(analysis, null, 2)}
          </pre>
        </section>
      )}

      {generatedFilename && (
        <section className="card">
          <h2>Generated Resume</h2>

          <DocumentEditorComponent
            filename={generatedFilename}
          />
        </section>
      )}
    </div>
  );
}

export default App;