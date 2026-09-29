#include "graphcore/graphcore.hpp"
#include <iostream>
using namespace graphcore;
int main(int argc,char** argv) {
    try {
        GraphBuilder builder("approval-v1");
        builder.add_node("prepare",[](const State&,const Context&) {
            return NodeResult{{{"proposal","Publish the generated report"}}};
        });
        builder.add_node("approve",[](const State& state,const Context& ctx) {
            if(!ctx.resumed) return NodeResult{{},{},true,"Approve: "+state.at("proposal")+"?"};
            return NodeResult{{{"approved",ctx.response}},ctx.response=="yes"?"publish":"rejected"};
        });
        builder.add_node("publish",[](const State&,const Context&) {
            // Demonstration only; a real external write needs an idempotency key.
            return NodeResult{{{"result","Report approved (no external action performed)"}}};
        });
        builder.add_node("rejected",[](const State&,const Context&) {
            return NodeResult{{{"result","Report rejected"}}};
        });
        auto graph=builder.entry("prepare").edges("prepare",{"approve"})
            .edges("approve",{"publish","rejected"}).edges("publish",{END})
            .edges("rejected",{END}).compile();
        FileCheckpoint checkpoint(argc>2?argv[2]:"approval.checkpoint");
        Runtime runtime; RunOptions options;
        options.on_event=[](const std::string& event,const std::string& node) {
            std::cout << event << " [" << node << "]\n";
        };
        auto result=argc>1?runtime.resume(graph,checkpoint,std::string(argv[1]),options)
                          :runtime.invoke(graph,{},&checkpoint,options);
        if(result.suspended) std::cout << result.prompt << "\nRestart with: ./graphcore_demo yes [checkpoint-path]\n";
        else std::cout << result.state.at("result") << '\n';
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
