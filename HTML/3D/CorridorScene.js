import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.158/build/three.module.js";

export class CorridorScene {
    constructor(parentDiv) {
        this.parent = parentDiv;

        this.width = this.parent.clientWidth;   //window.innerWidth;
        this.height = this.parent.clientHeight;       //window.innerHeight / 2;

        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0xf4f4f8);

        this.camera = new THREE.PerspectiveCamera(60, this.width / this.height, 0.1, 1000);
        this.camera.position.set(0, 25, 25);
        this.camera.lookAt(0, 0, 0);

        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(this.width, this.height);
        this.parent.appendChild(this.renderer.domElement);

        this.addLights();
        this.buildCorridor();
        this.startAnimationLoop();
    }

    /* -------------------------------------------------------- */
    /* ILUMINACIÓN                                               */
    /* -------------------------------------------------------- */
    addLights() {
        const ambient = new THREE.AmbientLight(0x888888);
        this.scene.add(ambient);

        const dir = new THREE.DirectionalLight(0xffffff, 0.8);
        dir.position.set(5, 10, 7);
        this.scene.add(dir);
    }

    /* -------------------------------------------------------- */
    /* GENERADOR DE TEXTURAS PARA BALDOSAS                      */
    /* -------------------------------------------------------- */
    generateTileVariants(n, size = 256, chips = 150) {
        const arr = [];
        for (let k = 0; k < n; k++) {
            const c = document.createElement('canvas');
            c.width = c.height = size;
            const ctx = c.getContext('2d');

            const base = 220 + Math.floor((Math.random() - 0.5) * 18);
            ctx.fillStyle = `rgb(${base}, ${base}, ${base})`;
            ctx.fillRect(0, 0, size, size);

            for (let i = 0; i < chips; i++) {
                const x = Math.random() * size;
                const y = Math.random() * size;
                const r = 3 + Math.random() * 14;
                ctx.beginPath();

                for (let p = 0; p < 5; p++) {
                    const angle = (p / 5) * Math.PI * 2;
                    const rr = r * (0.5 + Math.random() * 1.0);
                    const px = x + Math.cos(angle) * rr;
                    const py = y + Math.sin(angle) * rr;
                    if (p === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
                }
                ctx.closePath();

                const gbase = 100 + Math.random() * 100;
                const rcol = Math.floor(gbase + (Math.random() - 0.5) * 30);
                const gcol = Math.floor(gbase + (Math.random() - 0.5) * 30);
                const bcol = Math.floor(gbase + (Math.random() - 0.5) * 30);

                ctx.fillStyle = `rgb(${rcol},${gcol},${bcol})`;
                ctx.fill();

                if (Math.random() < 0.12) {
                    ctx.strokeStyle = "rgba(0,0,0,0.06)";
                    ctx.lineWidth = Math.max(1, Math.random() * 2);
                    ctx.stroke();
                }
            }

            const tex = new THREE.CanvasTexture(c);
            tex.encoding = THREE.sRGBEncoding;
            tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
            tex.repeat.set(1, 1);

            arr.push(tex);
        }
        return arr;
    }

    /* -------------------------------------------------------- */
    /* ESCENARIO COMPLETO                                       */
    /* -------------------------------------------------------- */
    buildCorridor() {
        const corridorWidth = 60;
        const corridorLength = 200;
        const tileSize = 10 / 3;

        const tilesX = Math.round(corridorWidth / tileSize);
        const tilesZ = Math.round(corridorLength / tileSize);

        const tileVariants = 10;
        const variants = this.generateTileVariants(tileVariants);

        const tileGeo = new THREE.PlaneGeometry(tileSize, tileSize);
        const floorGroup = new THREE.Group();

        const jointGap = 0.002;
        const effectiveTile = tileSize - jointGap;

        for (let ix = 0; ix < tilesX; ix++) {
            for (let iz = 0; iz < tilesZ; iz++) {
                const variantIndex = Math.floor(Math.random() * variants.length);
                const tex = variants[variantIndex];

                const rotation = Math.floor(Math.random() * 4) * (Math.PI / 2);
                const mat = new THREE.MeshPhysicalMaterial({
                    map: tex,
                    roughness: 0.55 + Math.random() * 0.15,
                    metalness: 0.0,
                    clearcoat: 0.5,
                    clearcoatRoughness: 0.08 + Math.random() * 0.08,
                    side: THREE.DoubleSide
                });

                const tile = new THREE.Mesh(tileGeo, mat);
                tile.rotation.x = -Math.PI / 2;
                tile.position.x = (ix + 0.5) * tileSize - corridorWidth / 2;
                tile.position.z = (iz + 0.5) * tileSize - corridorLength / 2;
                tile.position.y = 0.0005;

                tex.center.set(0.5, 0.5);
                tex.rotation = rotation;

                tile.scale.set(effectiveTile / tileSize, 1, effectiveTile / tileSize);
                floorGroup.add(tile);
            }
        }

        this.scene.add(floorGroup);

        /* ==================== Paredes ==================== */
        const wallHeight = 30;
        const wallThickness = 0.5;
        const wallMaterial = new THREE.MeshStandardMaterial({ color: 0xfff5e1 });

        const leftWall = new THREE.Mesh(
            new THREE.BoxGeometry(wallThickness, wallHeight, corridorLength + 0.2),
            wallMaterial
        );
        leftWall.position.set(-corridorWidth / 2 - wallThickness / 2, wallHeight / 2, 0);
        this.scene.add(leftWall);

        const rightWall = new THREE.Mesh(
            new THREE.BoxGeometry(wallThickness, wallHeight, corridorLength + 0.2),
            wallMaterial
        );
        rightWall.position.set(corridorWidth / 2 + wallThickness / 2, wallHeight / 2, 0);
        this.scene.add(rightWall);

        /* ==================== Puertas ==================== */
        const doorInterval = 50;
        const doorPositionsZ = [];
        for (let z = -corridorLength / 2 + doorInterval / 2;
             z < corridorLength / 2;
             z += doorInterval) {
            doorPositionsZ.push(z);
        }

        const doorWidth = 9;
        const doorHeight = 20;
        const doorDepth = 0.5;
        const woodMat = new THREE.MeshStandardMaterial({
            color: 0x8b5a2b,
            metalness: 0.05,
            roughness: 0.6
        });

        for (let zpos of doorPositionsZ) {
            const rightDoor = new THREE.Mesh(
                new THREE.BoxGeometry(doorDepth, doorHeight, doorWidth),
                woodMat
            );
            rightDoor.position.set(corridorWidth / 2 + wallThickness / 2 + doorDepth / 2 - 0.5,
                                   doorHeight / 2, zpos);
            this.scene.add(rightDoor);

            const leftDoor = new THREE.Mesh(
                new THREE.BoxGeometry(doorDepth, doorHeight, doorWidth),
                woodMat
            );
            leftDoor.position.set(-corridorWidth / 2 - wallThickness / 2 - doorDepth / 2 + 0.5,
                                  doorHeight / 2, zpos);
            this.scene.add(leftDoor);
        }
    }

    /* -------------------------------------------------------- */
    /* LOOP DE ANIMACIÓN                                        */
    /* -------------------------------------------------------- */
    startAnimationLoop() {
        const loop = () => {
            requestAnimationFrame(loop);
            this.renderer.render(this.scene, this.camera);
        };
        loop();
    }

    /* -------------------------------------------------------- */
    /* Permite agregar objetos (como el robot)                  */
    /* -------------------------------------------------------- */
    add(object3D) {
        this.scene.add(object3D);
    }
}
