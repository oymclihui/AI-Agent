"use client";

interface InspirationPreviewFrameProps {
  html: string;
  tone?: string;
  featured?: boolean;
}

/** Mini browser chrome + scaled page preview (gallery thumbnail style). */
export function InspirationPreviewFrame({ html, tone = "blue", featured }: InspirationPreviewFrameProps) {
  return (
    <div className={`inspiration-device inspiration-device-tone-${tone}${featured ? " inspiration-device--featured" : ""}`}>
      <div className="inspiration-device-bar">
        <span className="inspiration-device-dot inspiration-device-dot-red" />
        <span className="inspiration-device-dot inspiration-device-dot-yellow" />
        <span className="inspiration-device-dot inspiration-device-dot-green" />
        <span className="inspiration-device-url">preview.html</span>
      </div>
      <div className="inspiration-device-screen">
        <div className="inspiration-preview-scaler" dangerouslySetInnerHTML={{ __html: html }} />
      </div>
      <div className="inspiration-device-shine" aria-hidden />
    </div>
  );
}
