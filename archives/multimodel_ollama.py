#!/usr/bin/env python3

import os

from crewai_tools.tools.scrape_website_tool.scrape_website_tool import ScrapeWebsiteTool
from dotenv import load_dotenv

# Load environment variables from .env file at the very beginning
load_dotenv()

import sys
import time
import json
from typing import Dict, Any, Optional
from pathlib import Path
import requests
from dataclasses import dataclass
from enum import Enum
# Core CrewAI imports
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai_tools import BraveSearchTool, FileReadTool, DirectoryReadTool


# Color codes for enhanced terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class ModelStrength(Enum):
    """Define each model's primary strength"""
    ANALYTICAL = "analytical_thinking"
    EXECUTION = "efficient_processing"
    REASONING = "advanced_reasoning"


@dataclass
class ModelConfig:
    """Configuration for each AI model"""
    name: str
    ollama_model: str
    strength: ModelStrength
    role: str
    description: str
    temperature: float
    context_window: int


class OllamaManager:
    """Manages Ollama model operations and health checks"""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"

    def check_ollama_status(self) -> bool:
        """Check if Ollama service is running"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def list_available_models(self) -> list:
        """Get list of downloaded models"""
        try:
            response = requests.get(f"{self.api_url}/tags")
            if response.status_code == 200:
                return [model['name'] for model in response.json().get('models', [])]
            return []
        except requests.exceptions.RequestException:
            return []

    def check_model_availability(self, model_name: str) -> bool:
        """Check if a specific model is available"""
        available_models = self.list_available_models()
        return any(model_name in model for model in available_models)

    def pull_model_if_needed(self, model_name: str) -> bool:
        """Download model if not available"""
        if self.check_model_availability(model_name):
            print(f"{Colors.OKGREEN}✓ Model {model_name} already available{Colors.ENDC}")
            return True

        print(f"{Colors.WARNING}⚠ Model {model_name} not found. Downloading...{Colors.ENDC}")
        print(f"{Colors.OKCYAN}This may take several minutes depending on model size{Colors.ENDC}")

        try:
            # Use subprocess for better control of the download process
            import subprocess
            result = subprocess.run(
                ["ollama", "pull", model_name],
                capture_output=True,
                text=True,
                timeout=1800  # 30 minute timeout
            )

            if result.returncode == 0:
                print(f"{Colors.OKGREEN}✓ Successfully downloaded {model_name}{Colors.ENDC}")
                return True
            else:
                print(f"{Colors.FAIL}✗ Failed to download {model_name}: {result.stderr}{Colors.ENDC}")
                return False

        except subprocess.TimeoutExpired:
            print(f"{Colors.FAIL}✗ Download timeout for {model_name}{Colors.ENDC}")
            return False
        except Exception as e:
            print(f"{Colors.FAIL}✗ Error downloading {model_name}: {str(e)}{Colors.ENDC}")
            return False


class MultiModelCrew:
    """Main class for managing the multi-model AI crew"""

    def __init__(self):
        self.ollama_manager = OllamaManager()
        self.models_config = self._setup_model_configurations()
        self.llms = {}
        self.agents = {}
        self.knowledge_base = {}
        # Initialize the search tool
        self.search_tool = BraveSearchTool()
        self.scrape_tool = ScrapeWebsiteTool()

    def _setup_model_configurations(self) -> Dict[str, ModelConfig]:
        """Configure each model with its optimal settings and role"""
        return {
            "analyst": ModelConfig(
                name="Qwen Analyst",
                ollama_model="qwen3:1.7b",
                strength=ModelStrength.ANALYTICAL,
                role="Problem Analyst",
                description="analytical thinking, problem decomposition, creating a ToDo list",
                temperature=0.3,  # Lower for more focused analysis
                context_window=32768
            ),
            "researcher": ModelConfig(
                name="DeepSeek Researcher",
                ollama_model="deepseek-r1:8b",  # <-- Use DeepSeek for research
                strength=ModelStrength.REASONING,
                role="Information Researcher",
                description="Accessing the internet and local files to gather information.",
                temperature=0.6,
                context_window=128000
            ),
            "synthesizer": ModelConfig(
                name="Gemma3 Synthesizer",
                ollama_model="gemma3:1b",  # <-- Use Gemma for synthesis
                strength=ModelStrength.EXECUTION,
                role="Solution Synthesizer",
                description="Synthesizes information into a final answer based on research.",
                temperature=0.6,
                context_window=32768
            )
        }

    def initialize_system(self) -> bool:
        """Initialize the entire multi-model system"""
        print(f"{Colors.HEADER}{Colors.BOLD}")
        print("🚀 Initializing Multi-Model AI Crew with Ollama")
        print("=" * 50)
        print(f"{Colors.ENDC}")

        # Check Ollama status
        if not self.ollama_manager.check_ollama_status():
            print(f"{Colors.FAIL}✗ Ollama service not running{Colors.ENDC}")
            print(f"{Colors.WARNING}Please start Ollama with: ollama serve{Colors.ENDC}")
            return False

        print(f"{Colors.OKGREEN}✓ Ollama service is running{Colors.ENDC}")

        # Download required models
        models_ready = True
        for config in self.models_config.values():
            if not self.ollama_manager.pull_model_if_needed(config.ollama_model):
                models_ready = False

        if not models_ready:
            print(f"{Colors.FAIL}✗ Some models failed to download{Colors.ENDC}")
            return False

        # Initialize LLM connections
        self._setup_llm_connections()

        print(f"{Colors.OKGREEN}✅ Multi-Model Crew initialized successfully!{Colors.ENDC}")
        return True

    def _setup_llm_connections(self):
        """Setup LLM connections to Ollama models"""
        print(f"{Colors.OKCYAN}⚙ Setting up LLM connections...{Colors.ENDC}")

        for key, config in self.models_config.items():
            try:
                self.llms[key] = LLM(
                    model=f"ollama/{config.ollama_model}",
                    base_url="http://localhost:11434",
                    temperature=config.temperature,
                    # Additional parameters for optimal performance
                    max_tokens=4096,  # Increased max_tokens
                    top_p=0.9,
                    frequency_penalty=0.0,
                    presence_penalty=0.0
                )
                print(f"{Colors.OKGREEN}  ✓ {config.name} connected{Colors.ENDC}")

            except Exception as e:
                print(f"{Colors.FAIL}  ✗ Failed to connect {config.name}: {str(e)}{Colors.ENDC}")
                raise

    def solve_problem(self, problem: str) -> str:
        """
        Main method to solve a problem using the multi-model crew.
        Creates fresh agents and tasks for each run to prevent state leakage.
        """

        print(f"{Colors.HEADER}{Colors.BOLD}")
        print("🔧 Multi-Model Problem Solving Session")
        print("=" * 40)
        print(f"{Colors.ENDC}")
        print(f"{Colors.OKBLUE}Problem: {problem}{Colors.ENDC}")
        print()

        # --- Create Agents ---
        # 1. Analyst Agent (Qwen3)
        analyst = Agent(
            role="Problem Analyst and Strategist",
            goal="First, analyze a problem to determine if it can be solved with internal logical reasoning or if it requires internet research. Then, create a precise plan that consist of either search or reasoning for the next agent to follow. Do not search over the internet, your job is to decide if the next agent needs to search the internet or not, along with a to-do list.",
            backstory="You are a master strategist. Your first step is always to determine the nature of the problem: does it require new information, or can it be solved with logic and existing knowledge? Based on this, you produce a clear, actionable plan that explicitly states whether to search the web or to use reasoning. You never execute the plan yourself; you only create it.",
            llm=self.llms["analyst"],
            verbose=True,
            allow_delegation=False
        )

        # 2. Researcher Agent (DeepSeek-R1)
        researcher = Agent(
            role="Conditional Information Processor",
            goal="Execute a plan from the Problem Analyst. You will either perform internet research or use your internal knowledge based *only* on the instructions in the plan. IF YOU PERFORM A SEARCH AND SCRAPE A WEBSITE, YOU MUST SUMMARIZE OR EXTRACT ONLY THE MOST RELEVANT INFORMATION FROM THE SCRAPED CONTENT THAT DIRECTLY ANSWERS THE ORIGINAL PROBLEM OR PLAN QUERY. DO NOT PASS RAW, UNPROCESSED LARGE TEXT BLOCKS TO THE NEXT AGENT. Your final output should be a concise, relevant report.",
            backstory="You are a hyper-efficient, silent processor. You follow plans with precision. If a plan requires reasoning, you provide a detailed report. If the plan requires a search, you perform the search, scrape the most relevant URL, AND THEN CRITICALLY, you process the scraped data by summarizing or extracting only the key points relevant to the original query, significantly reducing its size before passing it on. You understand that passing extremely large raw text blocks will cause failures.",
            llm=self.llms["researcher"],
            tools=[self.search_tool, self.scrape_tool],
            verbose=True,
            allow_delegation=False
        )

        # 3. Synthesizer Agent (Gemma3)
        synthesizer = Agent(
            role="Solution Synthesizer",
            goal="Methodically review the gathered information from the researcher and compile a final, comprehensive answer.",
            backstory="You are a focused writer. You DO NOT perform research. You receive a research report and your only job is to format it into a final, comprehensive answer that directly addresses the original user's question.",
            llm=self.llms["synthesizer"],
            verbose=True,
            allow_delegation=False
        )

        # --- Create Tasks for this specific run ---

        # Task 1: Analysis and Planning
        analysis_task = Task(
            description=f"""Analyze the following problem: '{problem}'.
                    First, decide if this problem requires an internet search to acquire new information or if it can be solved with logical reasoning alone.
                    Based on your decision, generate a plan.
                    If an internet search is required, begin your output with the single word "SEARCH" on the first line, followed by a numbered list of 2-4 specific search queries.
                    If no search is required, begin your output with the single word "REASON" on the first line, followed by a logical outline of steps to reason through the problem.""",
            expected_output="""A plan that starts with either "SEARCH" or "REASON" on the first line.
                    If the first line is "SEARCH", it is followed by a numbered list of actionable search queries.
                    If the first line is "REASON", it is followed by a conceptual outline for solving the problem using logic.""",
            agent=analyst,
        )

        # Task 2: Research and Information Gathering
        research_task = Task(
            description=f"""Read the plan provided by the Problem Analyst.
                                    - If the plan says "SEARCH", perform the search. Then, take the most relevant URL from the search results and use the scrape tool to read its content.
                                    ***CRITICAL STEP***: AFTER SCRAPING THE CONTENT, YOU MUST PROCESS IT. Summarize or extract only the most relevant information from the scraped webpage that directly addresses the original problem or the specific search query from the plan. DO NOT include the entire scraped text in your final output. The goal is to drastically reduce the amount of text passed to the next agent.
                                    - If the plan says "REASON", use your internal knowledge to answer.
                                    Your final output should be the processed, concise information you gathered, whether from the summarized scraped content or internal knowledge.""",
            expected_output="""A detailed but CONCISE report of the information gathered. If data was scraped, this report MUST be a significantly summarized or extracted version of the scraped content, focusing only on the most relevant parts. This processed report will be passed to the synthesizer.""",
            agent=researcher,
            context=[analysis_task]
        )

        # Task 3: Synthesis and Final Solution
        synthesis_task = Task(
            description="""You have been given a report by the 'Conditional Information Processor'. Your task is to compile this information into a final, well-structured answer.
                    Do not add new information or deviate from the provided report.
                    Base your entire final answer on the results from the report.""",
            expected_output="A comprehensive, well-structured final answer that is the direct result of the research or reasoning. The answer must directly address the original problem.",
            agent=synthesizer,
            context=[research_task]
        )
        # --- Create and configure the crew with the fresh components ---
        crew = Crew(
            agents=[analyst, researcher, synthesizer],
            tasks=[analysis_task, research_task, synthesis_task],
            process=Process.sequential,
            verbose=True,
            memory=False,
            max_rpm=30,
            embedder={
                "provider": "ollama",
                "config": {
                    "model": "nomic-embed-text",
                    "base_url": "http://localhost:11434"
                }
            }
        )

        # Execute the crew workflow
        try:
            print(f"{Colors.OKCYAN}🚀 Starting collaborative problem solving...{Colors.ENDC}")
            result = crew.kickoff(inputs={'problem': problem})

            print(f"\n{Colors.OKGREEN}")
            print("=" * 50)
            print("✅ PROBLEM SOLVED SUCCESSFULLY!")
            print("=" * 50)
            print(f"{Colors.ENDC}")

            return str(result)

        except Exception as e:
            print(f"{Colors.FAIL}\n✗ Error during problem solving: {str(e)}{Colors.ENDC}")
            return f"Error: {str(e)}"

def main():
    """Main execution function"""

    # Initialize the multi-model crew
    crew_system = MultiModelCrew()

    if not crew_system.initialize_system():
        print(f"{Colors.FAIL}Failed to initialize system. Exiting.{Colors.ENDC}")
        sys.exit(1)

    # Example problems to test the system
    test_problems = [
        "What are the key differences in architecture and performance between RISC-V and ARM processors, and what are the implications for the future of mobile computing?",
        "Design a sustainable energy solution for a small rural community with limited grid access.",
        "Analyze the potential impact of quantum computing on current encryption methods and propose transition strategies."
    ]

    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("🎯 Multi-Model AI Crew Ready!")
    print(f"{Colors.ENDC}")
    print(f"{Colors.OKCYAN}Choose a test problem or enter your own:{Colors.ENDC}")

    for i, problem in enumerate(test_problems, 1):
        print(f"{Colors.OKBLUE}{i}. {problem[:80]}...{Colors.ENDC}")

    print(f"{Colors.OKBLUE}{len(test_problems) + 1}. Enter custom problem{Colors.ENDC}")
    print(f"{Colors.OKBLUE}0. Exit{Colors.ENDC}")

    while True:
        try:
            choice = input(f"\n{Colors.WARNING}Enter your choice (0-{len(test_problems) + 1}): {Colors.ENDC}")
            choice = int(choice)

            if choice == 0:
                print(f"{Colors.OKGREEN}Goodbye! 👋{Colors.ENDC}")
                break
            elif 1 <= choice <= len(test_problems):
                problem = test_problems[choice - 1]
                result = crew_system.solve_problem(problem)
                print(f"\n{Colors.OKGREEN}Final Result:{Colors.ENDC}")
                print(result)
            elif choice == len(test_problems) + 1:
                problem = input(f"{Colors.WARNING}Enter your problem: {Colors.ENDC}")
                if problem.strip():
                    result = crew_system.solve_problem(problem)
                    print(f"\n{Colors.OKGREEN}Final Result:{Colors.ENDC}")
                    print(result)
            else:
                print(f"{Colors.FAIL}Invalid choice. Please try again.{Colors.ENDC}")

        except ValueError:
            print(f"{Colors.FAIL}Please enter a valid number.{Colors.ENDC}")
        except KeyboardInterrupt:
            print(f"\n{Colors.OKGREEN}Goodbye! 👋{Colors.ENDC}")
            break
        except Exception as e:
            print(f"{Colors.FAIL}Error: {str(e)}{Colors.ENDC}")


if __name__ == "__main__":
    main()