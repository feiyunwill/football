#pragma once
#include <array>
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <span>

// Inference-only adapters, not modifications to categorical argmax or PPO.
class DeterministicInference {
 public:
  explicit DeterministicInference(std::string mode):mode_(std::move(mode)) {
    if(mode_!="balanced" && mode_!="repeat8") throw std::invalid_argument("Unknown deterministic controller");
  }
  int choose(std::span<const double> p) {
    if(p.size()!=19 || decisions_>=1000000) throw std::invalid_argument("Controller action/counter budget");
    double sum=0;for(double value:p) {
      if(!std::isfinite(value) || value<0 || value>1) throw std::invalid_argument("Invalid probability");
      sum+=value;
    }
    if(std::abs(sum-1)>1e-10) throw std::invalid_argument("Probabilities not normalized");
    int selected=0;
    if(mode_=="balanced") {
      for(size_t i=0;i<19;++i) credit_[i]+=p[i];
      selected=std::max_element(credit_.begin(),credit_.end())-credit_.begin();
      credit_[selected]-=1;
    } else {
      selected=std::max_element(p.begin(),p.end())-p.begin();
      if(selected==previous_ && repeated_>=8) {
        int second=selected==0?1:0;
        for(int i=0;i<19;++i) if(i!=selected && p[i]>p[second]) second=i;
        selected=second;
      }
    }
    repeated_=selected==previous_ ? repeated_+1 : 1;previous_=selected;++decisions_;
    return selected;
  }
  std::string get_state() const {
    std::ostringstream out;out<<std::setprecision(17)<<"DIC1 "<<mode_<<' '<<decisions_<<' '<<previous_<<' '<<repeated_;
    for(double value:credit_)out<<' '<<value;
    return out.str();
  }
  void set_state(const std::string& bytes) {
    if(bytes.size()>4096) throw std::invalid_argument("Controller state budget");
    std::istringstream in(bytes);std::string magic,mode,extra;size_t decisions,repeated;int previous;
    std::array<double,19> credit;
    if(!(in>>magic>>mode>>decisions>>previous>>repeated) || magic!="DIC1" || mode!=mode_ || decisions>1000000)
      throw std::invalid_argument("Invalid controller state identity");
    for(double& value:credit) if(!(in>>value) || !std::isfinite(value) || std::abs(value)>1000000)
      throw std::invalid_argument("Invalid controller credit");
    double credit_sum=0;for(double value:credit)credit_sum+=value;
    if(std::abs(credit_sum)>1e-6 || ((mode_=="repeat8" || decisions==0) &&
       std::any_of(credit.begin(),credit.end(),[](double v){return v!=0;})))
      throw std::invalid_argument("Inconsistent controller credits");
    if(in>>extra) throw std::invalid_argument("Trailing controller state data");
    if((decisions==0 && (previous!=-1 || repeated!=0)) ||
       (decisions>0 && (previous<0 || previous>=19 || repeated<1 || repeated>decisions)))
      throw std::invalid_argument("Inconsistent controller counters");
    decisions_=decisions;previous_=previous;repeated_=repeated;credit_=credit;
  }
 private:
  std::string mode_;
  std::array<double,19> credit_{};
  size_t decisions_=0,repeated_=0;
  int previous_=-1;
};
