pipeline {
  agent any
  options { timestamps() }
  stages {
    stage('Checkout') { steps { checkout scm } }
    stage('Bootstrap') { steps { sh 'make bootstrap' } }
    stage('Format check') { steps { sh 'set -a; [ ! -f .env.local ] || . ./.env.local; set +a; uv run ruff format --check services tests infrastructure/cdk && pnpm --dir apps/web format:check' } }
    stage('Lint') { steps { sh 'make lint' } }
    stage('Typecheck') { steps { sh 'make typecheck' } }
    stage('Unit tests') { steps { sh 'make test' } }
    stage('Frontend and Lambda build') { steps { sh 'make build' } }
    stage('CDK synth') { steps { sh 'make infra-synth' } }
    stage('Local integration') { steps { sh 'make up && make test-integration' } post { always { sh 'make down' } } }
    stage('Deploy integration') {
      when { branch 'main' }
      steps {
        input message: 'Deploy to integration?', ok: 'Deploy'
        withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'aws-integration-deploy']]) {
          sh 'make infra-deploy STAGE=integration'
          sh 'make test-e2e'
        }
      }
    }
  }
}
