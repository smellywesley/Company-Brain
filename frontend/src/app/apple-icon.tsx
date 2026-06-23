import { ImageResponse } from "next/og";

// iOS uses the apple-touch-icon (not the manifest icons) for the home screen.
// Generated as a real PNG at build via next/og.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0B0D12",
          color: "#818CF8",
          fontSize: 96,
          fontWeight: 700,
          letterSpacing: -4,
        }}
      >
        CB
      </div>
    ),
    { ...size }
  );
}
