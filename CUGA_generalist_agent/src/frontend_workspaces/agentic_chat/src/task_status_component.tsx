import React, { useState } from "react";
export default function TaskStatusDashboard({ taskData }) {
  const [showFullThoughts, setShowFullThoughts] = useState(false);

  // Sample data - you can replace this with props

  const {
    thoughts,
    subtasks_progress,
    next_subtask,
    next_subtask_type,
    next_subtask_app,
    conclude_task,
    conclude_final_answer,
  } = taskData;

  const total = subtasks_progress.length;
  const completed = subtasks_progress.filter((status) => status === "completed").length;
  const progressPercentage = (completed / total) * 100;

  function getStatusIcon(status) {
    if (status === "completed") return "✅";
    if (status === "in-progress") return "🔄";
    if (status === "not-started") return "⏳";
    return "❓";
  }

  function getAppIcon(app) {
    if (!app) return "🔧";
    const appLower = app.toLowerCase();
    if (appLower === "gmail") return "📧";
    if (appLower === "calendar") return "📅";
    if (appLower === "drive") return "📁";
    if (appLower === "sheets") return "📊";
    return "🔧";
  }

  function getTypeColor(type) {
    if (type === "api") return "bg-blue-100 text-blue-800";
    if (type === "analysis") return "bg-purple-100 text-purple-800";
    if (type === "calculation") return "bg-green-100 text-green-800";
    return "bg-gray-100 text-gray-800";
  }

  function truncateText(text, maxLength = 80) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  // Create a summary of thoughts
  function getThoughtsSummary() {
    if (thoughts.length === 0) return "No thoughts recorded";
    const firstThought = truncateText(thoughts[0], 100);
    return firstThought;
  }

  return (
    <div className="p-3">
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700">Task Progress</h3>
            <span
              className={`px-2 py-1 rounded text-xs font-medium ${
                conclude_task ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
              }`}
            >
              {conclude_task ? "Complete" : "Active"}
            </span>
          </div>

          {/* Progress Section */}
          <div className="mb-3 p-2 bg-gray-50 rounded border">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-600">Subtasks</span>
              <span className="text-xs text-gray-500">{completed}/{total}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex-1 bg-gray-200 rounded-full h-1.5">
                <div
                  className="bg-green-500 h-1.5 rounded-full transition-all duration-300"
                  style={{ width: `${progressPercentage}%` }}
                ></div>
              </div>
              <div className="flex gap-1">
                {subtasks_progress.map((status, index) => (
                  <span
                    key={index}
                    className="text-sm hover:scale-110 transition-transform cursor-pointer"
                    title={`Task ${index + 1}: ${status.replace("-", " ")}`}
                  >
                    {getStatusIcon(status)}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Next Action */}
          <div className="mb-3 p-2 bg-blue-50 rounded border border-blue-200">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm">🎯</span>
              <span className="text-xs text-gray-600">Next:</span>
              <span className={`px-1.5 py-0.5 rounded text-xs ${getTypeColor(next_subtask_type)}`}>
                {next_subtask_type}
              </span>
              {next_subtask_app && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 bg-white rounded text-xs text-gray-600 border">
                  {getAppIcon(next_subtask_app)} {next_subtask_app}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-700 leading-relaxed pl-5">{next_subtask}</p>
          </div>

          {/* Final Answer Section (if available) */}
          {conclude_final_answer && (
            <div className="mb-3 p-2 bg-green-50 rounded border border-green-200">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm">🎉</span>
                <span className="text-xs text-green-700 font-medium">Result</span>
              </div>
              <p className="text-xs text-green-600">{conclude_final_answer}</p>
            </div>
          )}

          {/* Thoughts Section - Collapsible */}
          <div className="border-t border-gray-100 pt-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">💭</span>
                <span className="text-xs text-gray-500">Analysis ({thoughts.length})</span>
                <button
                  onClick={() => setShowFullThoughts(!showFullThoughts)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  {showFullThoughts ? "▲" : "▼"}
                </button>
              </div>
            </div>
            
            {!showFullThoughts && (
              <p className="text-xs text-gray-400 italic mt-1">{getThoughtsSummary()}</p>
            )}

            {showFullThoughts && (
              <div className="mt-2 space-y-1">
                {thoughts.map((thought, index) => (
                  <div key={index} className="flex items-start gap-2">
                    <span className="text-xs text-gray-300 mt-0.5 font-mono">{index + 1}.</span>
                    <p className="text-xs text-gray-500 leading-relaxed">{thought}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
