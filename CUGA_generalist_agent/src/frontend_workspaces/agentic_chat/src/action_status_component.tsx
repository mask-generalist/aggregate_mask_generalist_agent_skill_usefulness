import React, { useState } from "react";

export default function ActionStatusDashboard({ actionData }) {
  const [showFullThoughts, setShowFullThoughts] = useState(false);

  // Sample data - you can replace this with props

  const { thoughts, action, action_input_shortlisting_agent, action_input_coder_agent, action_input_conclude_task } =
    actionData;

  function truncateText(text, maxLength = 80) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  function getThoughtsSummary() {
    if (thoughts.length === 0) return "No thoughts recorded";
    const firstThought = truncateText(thoughts[0], 100);
    return firstThought;
  }

  function getActionIcon(actionType) {
    switch (actionType) {
      case "CoderAgent":
        return "👨‍💻";
      case "ShortlistingAgent":
        return "📋";
      case "conclude_task":
        return "🎯";
      default:
        return "⚡";
    }
  }

  function getActionColor(actionType) {
    switch (actionType) {
      case "CoderAgent":
        return "bg-purple-100 text-purple-800 border-purple-200";
      case "ShortlistingAgent":
        return "bg-blue-100 text-blue-800 border-blue-200";
      case "conclude_task":
        return "bg-green-100 text-green-800 border-green-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  }

  // Determine which action is active
  const activeAction = action;
  const activeActionInput = action_input_coder_agent || action_input_shortlisting_agent || action_input_conclude_task;

  return (
    <div className="p-3">
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700">Active Action</h3>
            <span className={`px-2 py-1 rounded text-xs font-medium ${getActionColor(activeAction)}`}>
              {getActionIcon(activeAction)} {activeAction}
            </span>
          </div>

          {/* Active Action Details */}
          {activeActionInput && (
            <div className={`mb-3 p-2 rounded border ${getActionColor(activeAction)}`}>
              {/* Coder Agent */}
              {action_input_coder_agent && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-sm">👨‍💻</span>
                    <span className="text-xs font-medium text-purple-700">Coder Agent Task</span>
                  </div>
                  <p className="text-xs text-purple-600 leading-relaxed mb-2">
                    {action_input_coder_agent.task_description}
                  </p>
                  
                  {action_input_coder_agent.context_variables_from_history &&
                    action_input_coder_agent.context_variables_from_history.length > 0 && (
                      <div className="mb-2">
                        <span className="text-xs text-purple-600">Context:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {action_input_coder_agent.context_variables_from_history.slice(0, 3).map((variable, index) => (
                            <span
                              key={index}
                              className="px-1.5 py-0.5 bg-purple-50 text-purple-600 rounded text-xs"
                            >
                              {variable}
                            </span>
                          ))}
                          {action_input_coder_agent.context_variables_from_history.length > 3 && (
                            <span className="text-xs text-purple-500">
                              +{action_input_coder_agent.context_variables_from_history.length - 3} more
                            </span>
                          )}
                        </div>
                      </div>
                    )}

                  {action_input_coder_agent.relevant_apis && action_input_coder_agent.relevant_apis.length > 0 && (
                    <div>
                      <span className="text-xs text-purple-600">APIs:</span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {action_input_coder_agent.relevant_apis.slice(0, 2).map((api, index) => (
                          <span key={index} className="px-1.5 py-0.5 bg-purple-50 text-purple-600 rounded text-xs">
                            {api.api_name}
                          </span>
                        ))}
                        {action_input_coder_agent.relevant_apis.length > 2 && (
                          <span className="text-xs text-purple-500">
                            +{action_input_coder_agent.relevant_apis.length - 2} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Shortlisting Agent */}
              {action_input_shortlisting_agent && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-sm">📋</span>
                    <span className="text-xs font-medium text-blue-700">Shortlisting Agent Task</span>
                  </div>
                  <p className="text-xs text-blue-600 leading-relaxed">
                    {action_input_shortlisting_agent.task_description}
                  </p>
                </div>
              )}

              {/* Conclude Task */}
              {action_input_conclude_task && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-sm">🎯</span>
                    <span className="text-xs font-medium text-green-700">Task Conclusion</span>
                  </div>
                  <p className="text-xs text-green-600 leading-relaxed">{action_input_conclude_task.final_response}</p>
                </div>
              )}
            </div>
          )}

          {/* Action Status Overview */}
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div
              className={`p-2 rounded text-center text-xs ${
                action_input_coder_agent ? "bg-purple-100 text-purple-700" : "bg-gray-50 text-gray-400"
              }`}
            >
              <div className="text-sm mb-1">👨‍💻</div>
              <div className="font-medium">Coder</div>
              <div className="text-xs">{action_input_coder_agent ? "Active" : "Inactive"}</div>
            </div>

            <div
              className={`p-2 rounded text-center text-xs ${
                action_input_shortlisting_agent ? "bg-blue-100 text-blue-700" : "bg-gray-50 text-gray-400"
              }`}
            >
              <div className="text-sm mb-1">📋</div>
              <div className="font-medium">Shortlister</div>
              <div className="text-xs">{action_input_shortlisting_agent ? "Active" : "Inactive"}</div>
            </div>

            <div
              className={`p-2 rounded text-center text-xs ${
                action_input_conclude_task ? "bg-green-100 text-green-700" : "bg-gray-50 text-gray-400"
              }`}
            >
              <div className="text-sm mb-1">🎯</div>
              <div className="font-medium">Conclude</div>
              <div className="text-xs">{action_input_conclude_task ? "Active" : "Inactive"}</div>
            </div>
          </div>

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
