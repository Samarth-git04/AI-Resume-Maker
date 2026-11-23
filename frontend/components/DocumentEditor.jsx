import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { DocumentEditor } from "@onlyoffice/document-editor-react";
import { getEditorConfig, getResumeDownloadUrl } from "../services/api";

function DocumentEditorComponent({ filename }) {
  const [config, setConfig] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

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

  return createPortal(
    <div className="editor-workspace">
      <div className="document-editor-container">
        <div className="editor-toolbar">
          <a href={getResumeDownloadUrl(filename)} download>
            Download Resume
          </a>
        </div>

        <div className="onlyoffice-container">
          {error ? (
            <p className="editor-error">Error: {error}</p>
          ) : !config ? (
            <p className="editor-loading">Loading document editor...</p>
          ) : (
            <DocumentEditor
              id="onlyoffice-editor"
              documentServerUrl="http://localhost:8080"
              config={config}
            />
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

export default DocumentEditorComponent;