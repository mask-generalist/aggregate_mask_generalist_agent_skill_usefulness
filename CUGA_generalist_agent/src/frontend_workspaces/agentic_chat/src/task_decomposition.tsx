import React, { useState } from "react";
export default function TaskDecompositionComponent({ decompositionData }) {
  const [showFullThoughts, setShowFullThoughts] = useState(false);

  // Extract data from props
  const { thoughts, task_decomposition } = decompositionData;

  function getAppIcon(appName) {
    switch (appName?.toLowerCase()) {
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
      default:
        return "🔧";
    }
  }

  function getAppColor(appName) {
    switch (appName?.toLowerCase()) {
      case "gmail":
        return "bg-red-100 text-red-800 border-red-200";
      case "phone":
        return "bg-blue-100 text-blue-800 border-blue-200";
      case "venmo":
        return "bg-green-100 text-green-800 border-green-200";
      case "calendar":
        return "bg-purple-100 text-purple-800 border-purple-200";
      case "drive":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  }

  function getStepNumber(index) {
    return String(index + 1).padStart(2, "0");
  }

  function truncateThoughts(text, maxLength = 120) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  return (
    <div className="p-3">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <span className="text-sm">📋</span>
              Task Breakdown
            </h3>
            <span className="px-2 py-1 rounded text-xs bg-blue-100 text-blue-700">
              {task_decomposition.length} steps planned
            </span>
          </div>

          {/* Task Steps */}
          <div className="space-y-2 mb-3">
            {task_decomposition.map((task, index) => (
              <div key={index} className="relative">
                <div className="flex items-start gap-3">
                  {/* Step Number Circle */}
                  <div className="flex-shrink-0 w-6 h-6 bg-blue-500 text-white rounded-full flex items-center justify-center font-bold text-xs">
                    {getStepNumber(index)}
                  </div>

                  {/* Task Content */}
                  <div className="flex-1 bg-gray-50 rounded p-2 border">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${getAppColor(task.app)}`}
                      >
                        {getAppIcon(task.app)} {task.app}
                      </span>
                      <span className="px-1.5 py-0.5 bg-white rounded text-xs text-gray-600 border">{task.type}</span>
                    </div>
                    <p className="text-xs text-gray-700 leading-relaxed">{task.task}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Thoughts Section - Collapsible */}
          <div className="border-t border-gray-100 pt-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">💭</span>
                <span className="text-xs text-gray-500">Analysis</span>
                <button
                  onClick={() => setShowFullThoughts(!showFullThoughts)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  {showFullThoughts ? "▲" : "▼"}
                </button>
              </div>
            </div>
            
            {!showFullThoughts && (
              <p className="text-xs text-gray-400 italic mt-1">{truncateThoughts(thoughts, 80)}</p>
            )}

            {showFullThoughts && (
              <div className="mt-2 space-y-1">
                <p className="text-xs text-gray-500 leading-relaxed">{thoughts}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
