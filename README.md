# marint-naturkart-niva

Code for marine nature mapping project 2025-2026.

## Quick Start

Install dependencies using [pixi](https://pixi.prefix.dev/latest/installation/):

```bash
pixi install
```

## Workflow

1. **Labelling** - Extract training labels from NGU sediment data
2. **Modelling** - Train XGBoost classifier on bathymetric features
3. **Prediction** - Generate substrate maps for Norwegian waters
4. **Validation** - Evaluate model performance

See [notebooks](./notebooks/) for detailed implementation.

## Visualization

View results at [terriamap.p.niva.no](https://terriamap.p.niva.no/#share=g-654c56fd422dcc340046eeb6a81a57c4)


