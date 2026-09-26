import React, { useState } from "react";

export default function ShortlisterComponent({ shortlisterData }) {
  const [showFullThoughts, setShowFullThoughts] = useState(false);
  const [showAllApis, setShowAllApis] = useState(false);

  // Sample data for demonstration

  // Use props if provided, otherwise use sample data
  const { thoughts, result } = shortlisterData;

  const displayedApis = showAllApis ? result : result.slice(0, 2);
  const remainingCount = result.length - 2;

  function getScoreColor(score) {
    if (score >= 0.95) return "bg-green-100 text-green-800 border-green-300";
    if (score >= 0.9) return "bg-blue-100 text-blue-800 border-blue-300";
    if (score >= 0.8) return "bg-yellow-100 text-yellow-800 border-yellow-300";
    return "bg-gray-100 text-gray-800 border-gray-300";
  }

  function getScoreIcon(score) {
    if (score >= 0.95) return "🎯";
    if (score >= 0.9) return "✅";
    if (score >= 0.8) return "👍";
    return "📝";
  }

  function truncateApiName(name, maxLength = 30) {
    if (name.length <= maxLength) return name;
    return name.substring(0, maxLength) + "...";
  }

  function truncateThoughts(thoughtsArray, maxLength = 120) {
    const firstThought = thoughtsArray[0] || "";
    if (firstThought.length <= maxLength) return firstThought;
    return firstThought.substring(0, maxLength) + "...";
  }

  return (
    <div className="p-3">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <span className="text-sm">🔍</span>
              API Shortlist
            </h3>
            <span className="px-2 py-1 rounded text-xs bg-purple-100 text-purple-700">
              {result.length} APIs selected
            </span>
          </div>

          {/* Top APIs Preview */}
          <div className="space-y-2 mb-3">
            {displayedApis.map((api, index) => (
              <div key={index} className="border rounded p-2 hover:shadow-sm transition-shadow">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{getScoreIcon(api.relevance_score)}</span>
                    <div>
                      <h4 className="font-medium text-gray-800 text-xs">{truncateApiName(api.name, 25)}</h4>
                      <div className="flex items-center gap-2 mt-1">
                        <span
                          className={`px-1.5 py-0.5 rounded text-xs font-medium ${getScoreColor(
                            api.relevance_score
                          )}`}
                        >
                          {(api.relevance_score * 100).toFixed(0)}%
                        </span>
                        <span className="text-xs text-gray-500">#{index + 1}</span>
                      </div>
                    </div>
                  </div>
                </div>
                <p className="text-xs text-gray-600 leading-relaxed pl-5">{api.reasoning}</p>
              </div>
            ))}
          </div>

          {/* Show More/Less Button */}
          {result.length > 2 && (
            <div className="text-center mb-3">
              <button
                onClick={() => setShowAllApis(!showAllApis)}
                className="px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded text-xs font-medium transition-colors flex items-center gap-1 mx-auto"
              >
                <span>{showAllApis ? "Show less" : `Show ${remainingCount} more`}</span>
                <span className="text-xs">{showAllApis ? "▲" : "▼"}</span>
              </button>
            </div>
          )}

          {/* Quick Stats */}
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div className="text-center p-2 bg-green-50 rounded">
              <div className="text-sm font-bold text-green-700">
                {result.filter((api) => api.relevance_score >= 0.95).length}
              </div>
              <div className="text-xs text-green-600">High Priority</div>
            </div>
            <div className="text-center p-2 bg-blue-50 rounded">
              <div className="text-sm font-bold text-blue-700">
                {((result.reduce((sum, api) => sum + api.relevance_score, 0) / result.length) * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-blue-600">Avg Score</div>
            </div>
            <div className="text-center p-2 bg-purple-50 rounded">
              <div className="text-sm font-bold text-purple-700">{result.length}</div>
              <div className="text-xs text-purple-600">APIs Found</div>
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
              <p className="text-xs text-gray-400 italic mt-1">{truncateThoughts(thoughts, 80)}</p>
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
