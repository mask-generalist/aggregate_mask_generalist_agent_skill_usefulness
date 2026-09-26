#!/usr/bin/env python3
"""
Test runner for all registry tests
Runs all test suites in sequence with proper reporting
"""

import asyncio
import sys
import time
from typing import List, Tuple


# Import test modules
from test_legacy_openapi import run_legacy_tests
from test_mcp_server import run_mcp_tests
from test_mixed_configuration import run_mixed_tests
from test_e2e_api_registry import run_e2e_tests


class TestRunner:
    """Test runner with reporting"""

    def __init__(self):
        self.results: List[Tuple[str, bool, float, str]] = []

    async def run_test(self, name: str, test_func):
        """Run a single test and record results"""
        print(f"\n{'=' * 80}")
        print(f"🧪 RUNNING: {name}")
        print(f"{'=' * 80}")

        start_time = time.time()
        error_msg = ""

        try:
            await test_func()
            success = True
            print(f"\n✅ {name} PASSED")
        except Exception as e:
            success = False
            error_msg = str(e)
            print(f"\n❌ {name} FAILED: {error_msg}")
            import traceback

            traceback.print_exc()

        duration = time.time() - start_time
        self.results.append((name, success, duration, error_msg))

        return success

    def print_summary(self):
        """Print test summary"""
        print(f"\n{'=' * 80}")
        print("📊 TEST SUMMARY")
        print(f"{'=' * 80}")

        total_tests = len(self.results)
        passed_tests = sum(1 for _, success, _, _ in self.results if success)
        failed_tests = total_tests - passed_tests
        total_time = sum(duration for _, _, duration, _ in self.results)

        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Total Time: {total_time:.2f}s")
        print(f"Success Rate: {(passed_tests / total_tests * 100):.1f}%")

        print("\n📋 DETAILED RESULTS:")
        for name, success, duration, error_msg in self.results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"  {status} {name:<30} ({duration:.2f}s)")
            if error_msg:
                print(f"    Error: {error_msg}")

        if failed_tests == 0:
            print("\n🎉 ALL TESTS PASSED!")
        else:
            print(f"\n⚠️  {failed_tests} TEST(S) FAILED")

        return failed_tests == 0


async def main():
    """Main test runner"""
    print("🚀 Registry Test Suite")
    print("Running comprehensive tests for the Tools Environment Registry")

    runner = TestRunner()

    # Define test suite
    test_suite = [
        ("Legacy OpenAPI Integration", run_legacy_tests),
        ("MCP Server Integration", run_mcp_tests),
        ("Mixed Configuration Support", run_mixed_tests),
        ("E2E API Registry Server", run_e2e_tests),
    ]

    # Run all tests
    # all_passed = True
    for test_name, test_func in test_suite:
        success = await runner.run_test(test_name, test_func)
        if not success:
            # all_passed = False
            pass

    # Print final summary
    final_success = runner.print_summary()

    # Exit with appropriate code
    sys.exit(0 if final_success else 1)


if __name__ == "__main__":
    asyncio.run(main())
