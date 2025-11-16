class RoDifArm {
    constructor(scene, bus, options = {}) {
        this.bus = bus


   bus.subscribe("UDFJC/emb1/robot0/RPi/state", (msg) => {
        pose.beta = msg.w;
        pose.x += msg.v * Math.cos(pose.beta);
        pose.y += msg.v * Math.sin(pose.beta);

        pose.a0 = msg.alfa0;
        pose.a1 = msg.alfa1;
        pose.a2 = msg.alfa2;
    });



    bus.subscribe("UDFJC/emb1/robot0/RPi/sequence", (msg) => {
        if (msg.action === "create") {
            sequences[msg.sequence.name] = msg.sequence.states;
        }

        if (msg.action === "execute_now") {
            const seq = sequences[msg.name];
            if (!seq) return;
            runSequence(seq);
        }
    });


        this.state = {
            x: options.x ?? 0,
            y: options.y ?? 0,
            beta: options.beta ?? 0,
            alpha0: options.alpha0 ?? 0,
            alpha1: options.alpha1 ?? 0,
            alpha2: options.alpha2 ?? 0,
        };

        this.group = new THREE.Group();
        scene.add(this.group);

        this._build();

        this.sequences = {"ymca":[
          { v: 1, w: 0, alpha0: 0, time: 2 },
          { v: 0, w: -Math.PI / 4, alpha0: -Math.PI / 2, alpha1: 0, time: 2 },
          { v: vel_lin, w: omega, time: tiempo },
          {
            v: 0,
            w: 0,
            alpha0: Math.PI / 2,
            alpha1: (6 * Math.PI) / 16,
            alpha2: -(6 * Math.PI) / 16,
            time: 2,
          },
          { v: -vel_lin, w: omega, time: tiempo },
        ]};
        this.sequence = this.sequences["ymca"];
        this.currentStep = null;
        this.timeLeft = 0;
        this.initialAngles = {};
    }

    _build() {
        const base = new THREE.Mesh(
            new THREE.BoxGeometry(2, 0.5, 2),//(1, 0.3, .8),
            new THREE.MeshBasicMaterial({ color: 0x0077ff })
        );
        base.position.y = 0.3
        this.group.add(base);
        this.base = base;

        const wheelGeometry = new THREE.CylinderGeometry(0.4, 0.4, 0.5, 32);//(0.2, 0.2, 0.3, 32);
        const wheelMaterial = new THREE.MeshBasicMaterial({ color: 0x222222 });

        const wheelOffsets = [
            [0.7, 0.4, 1.2],
            [0.7, 0.4, -1.2],
            [-0.7, 0.4, 1.2],
            [-0.7, 0.4, -1.2],
        ];


        wheelOffsets.forEach(([x, y, z]) => {
            const wheel = new THREE.Mesh(wheelGeometry, wheelMaterial);
            wheel.rotation.x = Math.PI / 2;
            wheel.position.set(x, y, z);
            this.group.add(wheel);
        });

        const color_brazo = 0x00fff0;
        const a1 = 0.5;
        const a2 = 1;
        const a3 = 1;

        let geometry = new THREE.BoxGeometry(0.5, a1, 0.5);
        let material = new THREE.MeshBasicMaterial({ color: color_brazo });
        const armBase = new THREE.Mesh(geometry, material);
        armBase.translateY(a1 / 2);
        armBase.translateX(0.6);
        base.add(armBase);
        this.armBase = armBase;

        let shoulder = new THREE.Object3D();
        shoulder.translateY(a1 / 2);
        armBase.add(shoulder);
        this.shoulder = shoulder;

        geometry = new THREE.BoxGeometry(a2, 0.2, 0.2);
        let lowerArm = new THREE.Mesh(geometry, material);
        lowerArm.translateX(a2 / 2);
        shoulder.add(lowerArm);

        let elbow = new THREE.Object3D();
        elbow.translateX(a2 / 2);
        lowerArm.add(elbow);
        this.elbow = elbow;

        geometry = new THREE.BoxGeometry(a3, 0.1, 0.1);
        let arm = new THREE.Mesh(geometry, material);
        arm.translateX(a3 / 2);
        elbow.add(arm);

        let wrist = new THREE.Object3D();
        wrist.translateX(a3 / 2);
        arm.add(wrist);

        geometry = new THREE.TorusGeometry(0.1, 0.01, 3, 9, 5.6);
        let hand = new THREE.Mesh(geometry, material);
        hand.rotation.y = Math.PI / 2;
        hand.rotation.x = Math.PI / 2;
        wrist.add(hand);
    }

    moveTo(delta = {}) {
        Object.entries(delta).forEach(([key, value]) => {
            if (this.state.hasOwnProperty(key)) {
                this.state[key] += value;
            }
        });
    }

    addSequence(name, sequence) {
        this.sequences[name] = sequence;
        this.currentStep = null;
        this.timeLeft = 0;
        this.sequence = sequence
    }

    _startNextStep() {
        if (this.sequence.length === 0) {
            this.currentStep = null;
            return;
        }
        this.currentStep = this.sequence.shift();
        this.timeLeft = this.currentStep.time;

        this.initialAngles = {
            alpha0: this.state.alpha0,
            alpha1: this.state.alpha1,
            alpha2: this.state.alpha2,
        };
    }

    update(deltaTime) {
        if (!this.currentStep) {
            this._startNextStep();
            if (!this.currentStep) {
                this._render();
                return;
            }
        }

        const {
            x = this.state.x,
            y = this.state.y,
            beta = this.state.beta,
            v = this.state.v,
            w = this.state.w,
            alpha0 = this.state.alpha0,
            alpha1 = this.state.alpha1,
            alpha2 = this.state.alpha2,
        } = this.currentStep;

        this.state.x += v * Math.cos(this.state.beta) * deltaTime;
        this.state.y -= v * Math.sin(this.state.beta) * deltaTime;
        this.state.beta += (this.currentStep.w ?? 0) * deltaTime;

        const t = 1 - this.timeLeft / this.currentStep.time;

        ["alpha0", "alpha1", "alpha2"].forEach((key) => {
            if (this.currentStep[key] !== undefined) {
                const start = this.initialAngles[key];
                const end = this.currentStep[key];
                this.state[key] = start + (end - start) * t;
            }
        });

        this.timeLeft -= deltaTime;
        if (this.timeLeft <= 0) {
            this._startNextStep();
        }

        this._render();
    }

    _render() {
        this.group.position.set(this.state.x, 0, this.state.y);
        this.group.rotation.y = this.state.beta;

        this.armBase.rotation.y = this.state.alpha0;
        this.shoulder.rotation.z = this.state.alpha1;
        this.elbow.rotation.z = this.state.alpha2 - this.state.alpha1;
    }


 
    // async function runSequence(states) {
    //     for (const s of states) {
    //         pose.beta = s.w;
    //         pose.x += s.v * Math.cos(pose.beta);
    //         pose.y += s.v * Math.sin(pose.beta);
    //         pose.a0 = s.alfa0;
    //         pose.a1 = s.alfa1;
    //         pose.a2 = s.alfa2;
    //         await wait(s.duration * 1000);
    //     }
    // }

    // function wait(ms) {
    //     return new Promise(res => setTimeout(res, ms));
    // }


}

