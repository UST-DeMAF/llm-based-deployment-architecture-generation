# LLM-Based Deployment Architecture Generation

This repository contains the implementation, evaluation framework, datasets, and experimental results for the master's thesis:

> *LLM-Based Generation of Technology-Agnostic Deployment Architectures from Heterogeneous Infrastructure-as-Code Artifacts*

The project investigates how Large Language Models (LLMs) can transform heterogeneous Infrastructure-as-Code (IaC) deployment artifacts into technology-agnostic EDMM-based deployment architecture representations.

The repository includes:

- RAG-based transformation pipeline
- LLM-only baseline implementation
- Evaluation framework and semantic comparison metrics
- Deployment artifact datasets
- Expected EDMM reference models
- Generated evaluation results across multiple runs

## Supported Deployment Technologies

- Kubernetes
- Terraform
- Ansible

## Repository Structure

```text
Evaluation/       -> Evaluation datasets and deployment artifacts
Results/          -> Results of the RAG-based pipeline
ResultsNoRAG/     -> Results of the LLM-only baseline
rag.py            -> Main RAG-based pipeline
no_rag.py         -> Baseline LLM-only pipeline
batch_evaluate.py -> Batch evaluation execution
evaluate.py       -> Semantic evaluation scripts
```

## Evaluation

The evaluation compares generated EDMM models against manually constructed reference models using:

- Component-level metrics
- Relation-level metrics
- Attribute scores
- Graph similarity metrics

## Notes

This repository contains the implementation and evaluation artifacts used in the thesis experiments. Some runtime-specific resources (e.g., local vector databases and cached embeddings) are intentionally excluded from the repository.
