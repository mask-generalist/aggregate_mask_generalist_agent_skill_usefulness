import React, { useState } from "react";

export default function QaAgentComponent({ qaData }) {
  const [showFullThoughts, setShowFullThoughts] = useState(false);
  const [showFullAnswer, setShowFullAnswer] = useState(false);

  // Sample data for demonstration

  // Use props if provided, otherwise use sample data
  const { thoughts, name, answer } = qaData;

  function truncateThoughts(thoughtsArray, maxLength = 120) {
    const firstThought = thoughtsArray[0] || "";
    if (firstThought.length <= maxLength) return firstThought;
    return firstThought.substring(0, maxLength) + "...";
  }

  function truncateAnswer(answer, maxLength = 500) {
    if (answer.length <= maxLength) return answer;
    return answer.substring(0, maxLength) + "...";
  }

  function getAnswerPreview(answer) {
    const truncated = truncateAnswer(answer, 500);
    return truncated;
  }

  function getAnswerIcon(answer) {
    if (answer.length < 50) return "💡";
    if (answer.length < 200) return "📝";
    return "📄";
  }

  function getAnswerColor(answer) {
    if (answer.length < 50) return "bg-green-100 text-green-800 border-green-300";
    if (answer.length < 200) return "bg-blue-100 text-blue-800 border-blue-300";
    return "bg-purple-100 text-purple-800 border-purple-300";
  }

  const isAnswerTruncated = answer.length > 500;

  return (
    <div className="p-3">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <span className="text-sm">🔍</span>
              QA Agent Response
            </h3>
            <span className="px-2 py-1 rounded text-xs bg-emerald-100 text-emerald-700">Analysis Complete</span>
          </div>

          {/* Question Name */}
          <div className="mb-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs text-gray-500">Question:</span>
            </div>
            <h4 className="font-medium text-gray-800 text-xs bg-gray-50 rounded p-2 border">{name}</h4>
          </div>

          {/* Answer Section */}
          <div className="mb-3 border rounded p-2 hover:shadow-sm transition-shadow">
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-sm">{getAnswerIcon(answer)}</span>
                <div>
                  <span className="text-xs font-medium text-gray-700">Answer</span>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${getAnswerColor(answer)}`}>
                      {answer.length} chars
                    </span>
                    <span className="text-xs text-gray-500">{answer.split(" ").length} words</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="pl-5">
              <div className="bg-blue-50 border border-blue-200 rounded p-2">
                <p className="text-xs text-gray-700 leading-relaxed font-mono whitespace-pre-wrap">
                  {showFullAnswer ? answer : getAnswerPreview(answer)}
                </p>

                {isAnswerTruncated && (
                  <div className="mt-2 text-center">
                    <button
                      onClick={() => setShowFullAnswer(!showFullAnswer)}
                      className="px-2 py-1 bg-blue-100 hover:bg-blue-200 text-blue-700 rounded text-xs font-medium transition-colors flex items-center gap-1 mx-auto"
                    >
                      {showFullAnswer ? (
                        <>
                          <span>Show less</span>
                          <span className="text-xs">▲</span>
                        </>
                      ) : (
                        <>
                          <span>Show full answer</span>
                          <span className="text-xs">▼</span>
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Quick Stats */}
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div className="text-center p-2 bg-blue-50 rounded">
              <div className="text-sm font-bold text-blue-700">{thoughts.length}</div>
              <div className="text-xs text-blue-600">Analysis Steps</div>
            </div>
            <div className="text-center p-2 bg-green-50 rounded">
              <div className="text-sm font-bold text-green-700">{answer.length}</div>
              <div className="text-xs text-green-600">Answer Length</div>
            </div>
            <div className="text-center p-2 bg-purple-50 rounded">
              <div className="text-sm font-bold text-purple-700">{answer.split(" ").length}</div>
              <div className="text-xs text-purple-600">Words</div>
            </div>
          </div>

          {/* Thoughts Section - Collapsible */}
          <div className="border-t border-gray-100 pt-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">💭</span>
                <span className="text-xs text-gray-500">QA Analysis ({thoughts.length})</span>
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
