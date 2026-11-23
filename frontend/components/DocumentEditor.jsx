import { useEffect, useState } from "react";
import { DocumentEditor } from "@onlyoffice/document-editor-react";
import { getEditorConfig, getResumeDownloadUrl } from "../services/api";

function DocumentEditorComponent({ filename }) {
  const [config, setConfig] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadConfig() {
      try {
        setConfig(null);
        setError("");

        const data = await getEditorConfig(filename);

        if (!cancelled) {
          setConfig(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      }
    }

    loadConfig();

    return () => {
      cancelled = true;
    };
  }, [filename]);

  if (error) {
    return <p className="editor-error">Error: {error}</p>;
  }

  if (!config) {
    return <p className="editor-loading">Loading document editor...</p>;
  }

  return (
    <div className="document-editor-container">
      <div className="editor-toolbar">
        <a href={getResumeDownloadUrl(filename)} download>
          Download Resume
        </a>
      </div>

      <div className="onlyoffice-container">
        <DocumentEditor
          id="onlyoffice-editor"
          documentServerUrl="http://localhost:8080"
          config={config}
        />
      </div>
    </div>
  );
}

export default DocumentEditorComponent;