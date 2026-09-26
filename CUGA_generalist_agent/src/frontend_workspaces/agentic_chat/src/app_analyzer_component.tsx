import React, { useState } from "react";

interface AppData {
  name: string;
}

export default function AppAnalyzerComponent({ appData }: { appData: AppData[] }) {
  const [showAllApps, setShowAllApps] = useState(false);

  // Sample data - you can replace this with props

  function getAppIcon(appName: string) {
    switch (appName.toLowerCase()) {
      case "gmail":
        return "📧";
      case "phone":
        return "📱";
      case "venmo":
        return "💰";
      case "calendar":
        return "📅";
      case "drive":
        return "📁";
      case "sheets":
        return "📊";
      case "slack":
        return "💬";
      case "spotify":
        return "🎵";
      case "uber":
        return "🚗";
      case "weather":
        return "🌤️";
      default:
        return "🔧";
    }
  }

  function getAppColor(appName: string) {
    switch (appName.toLowerCase()) {
      case "gmail":
        return "bg-red-100 text-red-700";
      case "phone":
        return "bg-blue-100 text-blue-700";
      case "venmo":
        return "bg-green-100 text-green-700";
      case "calendar":
        return "bg-purple-100 text-purple-700";
      case "drive":
        return "bg-yellow-100 text-yellow-700";
      default:
        return "bg-gray-100 text-gray-700";
    }
  }

  const displayedApps = showAllApps ? appData : appData.slice(0, 4);

  return (
    <div className="p-3">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <span className="text-sm">🔍</span>
              App Analysis
            </h3>
            <span className="px-2 py-1 rounded text-xs bg-blue-100 text-blue-700">
              {appData.length} apps
            </span>
          </div>

          {/* Apps Display */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {displayedApps.map((app: AppData, index: number) => (
              <div key={index} className={`flex items-center gap-1.5 px-2 py-1 rounded ${getAppColor(app.name)}`}>
                <span className="text-sm">{getAppIcon(app.name)}</span>
                <span className="text-xs font-medium capitalize">{app.name}</span>
              </div>
            ))}
          </div>

          {/* Show More Button */}
          {appData.length > 4 && (
            <div className="mb-3">
              <button
                onClick={() => setShowAllApps(!showAllApps)}
                className="text-xs text-blue-600 hover:text-blue-800"
              >
                {showAllApps ? "▲ Less" : `▼ +${appData.length - 4} more`}
              </button>
            </div>
          )}

          {/* Status */}
          <div className="text-xs text-gray-500">
            ✅ Ready to use {appData.length} integrated services
          </div>
        </div>
      </div>
    </div>
  );
}
