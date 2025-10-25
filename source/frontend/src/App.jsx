import { useState, useEffect, useRef } from "react";

export default function App() {
  const [url, setUrl] = useState(import.meta.env.VITE_TARGETURL || "");
  const [targetTime, setTargetTime] = useState(
    import.meta.env.VITE_TARGETTIME || ""
  );
  const [keywords, setKeywords] = useState(import.meta.env.VITE_KEYWORDS || "");
  const [chromePath, setChromePath] = useState(
    import.meta.env.VITE_CHROMEPATH || ""
  );
  const [userDataDir, setUserDataDir] = useState(
    import.meta.env.VITE_DATADIR || ""
  );

  const [profileName, setProfileName] = useState(
    import.meta.env.VITE_PROFILENAME || ""
  );
  const [logs, setLogs] = useState([]);
  const wsRef = useRef(null);

  useEffect(() => {
    console.log(import.meta.env.VITE_TARGETTIME);
    let ws;
    let retries = 0;
    const maxRetries = 10;

    const connect = () => {
      if (retries >= maxRetries) return;

      ws = new WebSocket("ws://127.0.0.1:8000/ws");

      ws.onopen = () => {
        console.log("WebSocket connected");
        setLogs((prev) => [...prev, "WebSocket connected"]);
        wsRef.current = ws;
        retries = 0;
      };

      ws.onmessage = (event) => {
        setLogs((prev) => [...prev, event.data]);
      };

      ws.onclose = () => {
        console.log("WebSocket closed, retrying...");
        retries++;
        setTimeout(connect, 1000);
      };

      ws.onerror = () => {
        console.error("WebSocket error");
        if (ws.readyState !== WebSocket.CLOSED) ws.close();
      };
    };

    connect();

    return () => {
      if (ws && ws.readyState !== WebSocket.CLOSED) ws.close();
    };
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("url", url);
    formData.append("target_time", targetTime);
    formData.append("button_keywords", keywords);
    formData.append("chrome_path", chromePath);
    formData.append("user_data_dir", userDataDir);
    formData.append("profile_name", profileName);

    await fetch("http://127.0.0.1:8000/run", {
      method: "POST",
      body: formData,
    });
    setLogs((prev) => [...prev, "Task started..."]);
  };

  return (
    <div style={{ padding: "20px" }}>
      <h2>Selenium Scheduler</h2>
      <form onSubmit={handleSubmit}>
        URL: <input value={url} onChange={(e) => setUrl(e.target.value)} />
        <br />
        Target Time (YYYY-MM-DD HH:MM:SS):{""}
        <input
          value={targetTime}
          onChange={(e) => setTargetTime(e.target.value)}
        />
        <br />
        Button Keywords (comma separated):{" "}
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        <br />
        ChromeDriver Path:{" "}
        <input
          value={chromePath}
          onChange={(e) => setChromePath(e.target.value)}
        />
        <br />
        User Data Dir:{" "}
        <input
          value={userDataDir}
          onChange={(e) => setUserDataDir(e.target.value)}
        />
        <br />
        Profile Name:{" "}
        <input
          value={profileName}
          onChange={(e) => setProfileName(e.target.value)}
        />
        <br />
        <button type="submit">Run</button>
      </form>
      <h3>Logs</h3>
      <textarea rows={20} cols={80} value={logs.join("\n")} readOnly />
    </div>
  );
}
